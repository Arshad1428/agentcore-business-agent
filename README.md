# AgentCore Business Process Automation Agent

An AI agent built with **Strands Agents** and **AWS Bedrock AgentCore Runtime** that automates a
purchase-order business process: product lookup, quote, manager approval, order creation and
department notification.

It supports:

- **Configurable workflows**: ordered, declarative steps that run the same tools the agent uses
- **Tool integration**: Python `@tool` functions shared by the agent and the workflow engine
- **Execution management**: execution IDs, status tracking, and bounded, expiring sessions
- **Two run modes**: free-form requests handled by the model, or fixed workflows with no model call

## Architecture

```
                         AgentCore Runtime  (runtime.py entrypoint)
                                   |
        +--------------------------+---------------------------+
        |                          |                           |
  {"prompt": ...}          {"workflow": ...}            {"action": ...}
        |                          |                           |
  Strands Agent            Workflow engine              Execution / approval
  (model picks tools)      (fixed ordered steps)        management
        |                          |
        +------------- Tools ------+
   lookup_product, calculate_order_total, request_approval,
   create_order, get_order_status, send_notification, run_workflow
```

Business rules (quantity 1-50, valid department, product exists, stock, manager approval above
100,000 INR) are enforced inside the tools, so they hold in both run modes.

## Project layout

```
main.py                          local CLI (one-shot or interactive, prints tool trace)
src/business_agent/
  config.py                      environment configuration
  agent.py                       model provider + system prompt + tools -> Strands Agent
  runtime.py                     AgentCore Runtime entrypoint
  workflows.py                   workflow definitions + step engine
  executions.py                  session cache and execution records
  data/products.py               product catalog and business constants
  tools/                         lookup_product, calculate_order_total, request_approval,
                                 create_order, get_order_status, send_notification, run_workflow
tests/                           tool, workflow, execution, runtime and agent tests
iam/                             execution role policy template
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-local.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Set the model in `.env`:

- **Ollama (local):** `MODEL_PROVIDER=ollama`, then `ollama pull llama3.1`
- **Amazon Bedrock:** `MODEL_PROVIDER=bedrock`, `AWS_REGION=<region>`, `BEDROCK_MODEL_ID=<model-id>`

## Run

### Agent mode (the model decides which tools to call)

```bash
python main.py "Create an order for 3 monitors for the Engineering department." --trace
```

The trace shows the tools the model used. It will either call the tools one by one
(`lookup_product` -> `calculate_order_total` -> `create_order`) or call `run_workflow` once.
Other prompts to try:

| Prompt | Expected behavior |
|---|---|
| `Create an order for monitors.` | Asks for the missing quantity and department |
| `Order 5 quantum keyboards for Engineering.` | Reports the product does not exist |
| `Order 2 laptops for Finance.` | Needs manager approval, order is not created |
| `Write me a poem.` | Declines, uses no tools |

### Runtime server (agent, workflows and actions)

```bash
python src/business_agent/runtime.py        # serves on http://localhost:8080
```

```bash
curl -s -X POST localhost:8080/invocations -H "Content-Type: application/json" \
  -d '{"workflow":"purchase_order","inputs":{"product":"monitor","quantity":3,"department":"Engineering"}}'
```

Workflow and action requests do not call a model, so they work without Ollama or Bedrock.

## Workflows

Workflows are data in `WORKFLOWS` (`src/business_agent/workflows.py`).

| Workflow | Inputs | Steps |
|---|---|---|
| `purchase_order` | `product`, `quantity`, `department`, optional `approval_id` | lookup -> quote -> approval -> create -> notify |
| `order_status_check` | `order_id` | status |

Each step names a registered tool and its arguments. `"$input.x"` reads a workflow input and
`"$steps.<id>.<field>"` reads an earlier step's output. A step can set `pause_if` to pause the run
instead of failing it.

To add a workflow, add an entry with `description`, `inputs` and `steps`. No engine changes are needed.

The result `workflow_status` is one of:

- `completed`: every step succeeded
- `failed`: a step failed; the response includes `failed_step` and later steps show `skipped`
- `pending_approval`: the total is above the approval threshold; re-run with the `approval_id`
  after a manager approves

## Runtime payloads

```json
{"prompt": "Create an order for 3 monitors for Engineering."}
{"workflow": "purchase_order", "inputs": {"product": "laptop", "quantity": 2, "department": "Finance"}}
{"action": "list_workflows"}
{"action": "get_execution", "execution_id": "exe-..."}
{"action": "list_executions"}
{"action": "approve", "approval_id": "APR-..."}
```

`approve` is a manager action available only through the Runtime. It is not an agent tool, so the
model cannot approve its own requests.

### Approval example (2 laptops = 170,000 INR)

```bash
# 1. Returns workflow_status "pending_approval" and an approval_id
{"workflow":"purchase_order","inputs":{"product":"laptop","quantity":2,"department":"Finance"}}

# 2. Manager approves
{"action":"approve","approval_id":"APR-XXXXXXXX"}

# 3. Re-run with the approval_id; returns "completed"
{"workflow":"purchase_order","inputs":{"product":"laptop","quantity":2,"department":"Finance","approval_id":"APR-XXXXXXXX"}}
```

Send all three requests in the same Runtime session.

## Execution management

- Every request returns an `execution_id`. Records hold `kind` (agent or workflow), `status`,
  timings and tool-error counts, and are readable with `get_execution` and `list_executions`.
- Each session keeps its own agent conversation. Sessions are capped by `MAX_SESSIONS` and expire
  after `SESSION_TTL_SECONDS` of inactivity.
- Errors return a clean JSON body (`invalid_request`, `agent_execution_failed`,
  `workflow_step_failed`) with no stack traces.

## Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `MODEL_PROVIDER` | `ollama` or `bedrock` | `ollama` |
| `OLLAMA_HOST`, `OLLAMA_MODEL_ID` | Local model settings | `http://localhost:11434`, `llama3.1` |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | Required when using Bedrock | none |
| `MAX_SESSIONS` | Maximum concurrent sessions kept | `100` |
| `SESSION_TTL_SECONDS` | Idle session expiry | `1800` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `SIMULATE_TOOL_FAILURE` | `1` makes `create_order` raise, to test failure handling | `0` |

## Tests

```bash
# No model needed
pytest tests/test_tools.py tests/test_runtime.py tests/test_workflows.py tests/test_executions.py

# With a real model: happy path, missing info, unknown product, bad quantity,
# approval rule, out-of-scope request, tool failure
RUN_LLM_TESTS=1 pytest tests/test_agent.py -s
```

Run `export PYTHONPATH=src` first if `business_agent` cannot be imported
(Windows PowerShell: `$env:PYTHONPATH="src"`).

## Deploy to AgentCore Runtime

```bash
agentcore configure -e src/business_agent/runtime.py
agentcore launch --env MODEL_PROVIDER=bedrock --env AWS_REGION=<region> --env BEDROCK_MODEL_ID=<model-id>
agentcore invoke '{"workflow":"purchase_order","inputs":{"product":"monitor","quantity":3,"department":"Engineering"}}'
```

`iam/execution-role-policy.template.json` is a least-privilege starting point for the execution role.

## Logging

Each request logs `request_id`, session, execution ID, tool name and status, tool-error count and
latency. Prompts, tool inputs and order contents are not logged. In AgentCore, these logs appear in
CloudWatch under `/aws/bedrock-agentcore/runtimes/...`.
