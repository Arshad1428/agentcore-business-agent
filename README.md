# AgentCore Business Process Automation Agent

A single **Strands** agent that automates an internal purchase-order process
(product lookup → quote → manager approval → *simulated* order creation → notification),
available both as **configurable workflows** and as free-form LLM requests, with
**execution tracking**. It reasons with a
model (local **Ollama** by default, **Amazon Bedrock** optional), uses `@tool` Python
functions, and is wrapped for **Amazon Bedrock AgentCore Runtime**.

> Demonstrates: *"Built and deployed AI agents using AWS Bedrock AgentCore Runtime.
> Configure agent workflows, integrate tools, and manage agent execution for business
> process automation."*

## Architecture

```
User -> AgentCore Runtime -> runtime.py entrypoint -> Strands Agent -> Model (Bedrock | Ollama locally)
                                                          |  model decides which tool(s) to call
                                          lookup_product / calculate_order_total / create_order
                                                          |  results go back to the model
                                                      Final response (+ tool trace)
```

There are two ways to run the process:

1. **Agent mode** (`{"prompt": ...}`): the model receives the system prompt and tool
   definitions and Strands runs the reason → tool → reason loop. The model can also call
   the `run_workflow` tool.
2. **Workflow mode** (`{"workflow": ..., "inputs": ...}`): a *declarative* workflow
   (`workflows.py`) runs its steps in a fixed order, deterministically, with no LLM. Each
   step's output feeds later steps; the run stops on the first failure or pauses for
   approval.

Business rules (quantity 1-50, valid department, product exists, stock, **manager approval
above 100,000 INR**) are enforced **inside the tools**, not trusted to the LLM.

## Layout

```
main.py                         local CLI (one-shot or interactive, prints tool trace)
src/business_agent/config.py    env configuration only
src/business_agent/agent.py     model provider + system prompt + tools -> Strands Agent
src/business_agent/runtime.py   AgentCore Runtime entrypoint (wraps the same agent)
src/business_agent/workflows.py configurable workflows (data) + step engine
src/business_agent/executions.py bounded session cache (LRU + idle TTL) and execution records
src/business_agent/data/        demo catalog (fictional data)
src/business_agent/tools/       lookup_product, calculate_order_total, request_approval,
                                create_order, get_order_status, send_notification, run_workflow
tests/                          tool tests, runtime tests, LLM behaviour tests
iam/                            least-privilege execution role policy TEMPLATE
```

## Install

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-local.txt
cp .env.example .env
```

## Run locally (free, no AWS)

1. Install [Ollama](https://ollama.com), then `ollama pull llama3.1` (any tool-calling model works; set `OLLAMA_MODEL_ID`).
2. Make sure `.env` has `MODEL_PROVIDER=ollama`.

```bash
python main.py "Create an order for 3 monitors for the Engineering department." --trace
```

Expected trace (the model chooses this; verify it, don't just trust the answer):

```
1. lookup_product({"product_name": "monitor"}) -> success
2. calculate_order_total({"unit_price": 15000, "quantity": 3}) -> success   # optional
3. create_order({"product": "monitor", "quantity": 3, "department": "Engineering"}) -> success
```

Other prompts to try: `Create an order for monitors.` (should ask for missing info),
`Order 5 quantum keyboards for Engineering.` (unknown product), `Order -5 monitors.`
(tool rejects), `Write me a poem.` (declines, no tools).

Small local models are less reliable at tool calling than hosted ones; if a behaviour
test fails, check the trace before blaming the code.

## Workflows

Defined as data in `WORKFLOWS` (`src/business_agent/workflows.py`). To add one, add an entry
with `inputs` and ordered `steps`; each step names a registered tool and its `args`
(`"$input.x"` = workflow input, `"$steps.<id>.<field>"` = earlier step output). A step may
declare `pause_if` to pause (not fail) the run.

| Workflow | Inputs | Steps |
|---|---|---|
| `purchase_order` | product, quantity, department, *(approval_id)* | lookup → quote → approval → create → notify |
| `order_status_check` | order_id | status |

Result `workflow_status`: `completed`, `failed` (with `failed_step`; later steps are `skipped`), or
`pending_approval` (re-run with the `approval_id` once a manager approves).

## Runtime payloads

```json
{"prompt": "Create an order for 3 monitors for Engineering."}
{"workflow": "purchase_order", "inputs": {"product": "laptop", "quantity": 2, "department": "Finance"}}
{"action": "list_workflows"}
{"action": "get_execution", "execution_id": "exe-..."}
{"action": "list_executions"}
{"action": "approve", "approval_id": "APR-..."}
```

`approve` is a manager action exposed only through the Runtime. It is **not** an agent tool, so
the model can never approve its own request. In a real system, put it behind AgentCore Identity /
your own authorization.

Approval walkthrough (2 laptops = 170,000 INR > 100,000):

```bash
agentcore invoke '{"workflow":"purchase_order","inputs":{"product":"laptop","quantity":2,"department":"Finance"}}'   # pending_approval + approval_id
agentcore invoke '{"action":"approve","approval_id":"APR-XXXXXXXX"}'
agentcore invoke '{"workflow":"purchase_order","inputs":{"product":"laptop","quantity":2,"department":"Finance","approval_id":"APR-XXXXXXXX"}}'   # completed
```

State is in memory per process, so the three calls must reach the same Runtime session
(pass the same session ID on invoke).

## Execution management

Every request gets an `execution_id` and a record (`kind`, `status`, timings, tool errors).
Sessions are capped (`MAX_SESSIONS`) and expire when idle (`SESSION_TTL_SECONDS`), so a
long-running Runtime cannot grow without bound.

## Tests

```bash
pytest tests/test_tools.py tests/test_runtime.py tests/test_workflows.py tests/test_executions.py   # deterministic, free, no LLM
RUN_LLM_TESTS=1 pytest tests/test_agent.py -s        # real model: happy path, missing info,
                                                     # unknown product, bad qty, out-of-scope, tool failure
```

LLM tests assert on **which tools were called and what was created**, not exact wording.
With `MODEL_PROVIDER=bedrock` they consume paid tokens.

Controlled failure demo: `SIMULATE_TOOL_FAILURE=1 python main.py "Order 2 keyboards for HR"`
makes `create_order` raise; the agent must report that no order was created.

## Validate the Runtime wrapper locally (free with Ollama)

```bash
python src/business_agent/runtime.py          # serves on :8080
curl -s -X POST localhost:8080/invocations -H "Content-Type: application/json" \
  -d '{"prompt": "Create an order for 3 monitors for Engineering."}'
```

Agent response shape: `status`, `response`, `tool_calls` (name + status), `tool_errors`,
`execution_id`, `session_id`, `request_id`, `latency_ms`. Workflow responses carry
`workflow_status`, `failed_step`, `steps`, `execution_id` instead. A bad payload returns
`{"status":"error","error_type":"invalid_request"}` **without calling the model**; agent/model
exceptions return `agent_execution_failed` with no stack trace.

## Deploy to AgentCore Runtime (this step costs money)

A deployed Runtime cannot reach Ollama on your machine, so deployment **requires Bedrock**.

1. Configure AWS credentials (IAM user/role or SSO; never root, never commit keys).
2. In the Bedrock console, enable access to a small tool-capable model; put its ID in `.env`:
   `MODEL_PROVIDER=bedrock`, `AWS_REGION=...`, `BEDROCK_MODEL_ID=...`.
3. Smoke-test once locally with Bedrock (a few cents at most): `python main.py "Create an order for 3 monitors for Engineering." --trace`.
4. Deploy with the starter toolkit (check `agentcore <cmd> --help`; flags change between versions):

```bash
agentcore configure -e src/business_agent/runtime.py     # review the generated role/config
agentcore launch --env MODEL_PROVIDER=bedrock --env AWS_REGION=<region> --env BEDROCK_MODEL_ID=<model-id>
agentcore invoke '{"prompt": "Create an order for 3 monitors for Engineering."}'
```

Use `iam/execution-role-policy.template.json` as the basis for a custom least-privilege execution role
(pass it to `agentcore configure`, see its `--help`), instead of the auto-generated one if that is broader than you want.
**I could not verify the exact action list or CLI flags offline: confirm against current AWS docs.**

Minimal cloud validation (3 invocations is enough): (1) happy path, (2) invalid payload `{}`,
(3) a run with `SIMULATE_TOOL_FAILURE=1` set on the deployment. Then read the CloudWatch log group
for the runtime (`/aws/bedrock-agentcore/runtimes/...`) and look for `request_start`, `tool_call`,
`request_end`, `agent_error` lines. Sessions: pass a session ID on invoke so related calls share an agent/conversation.
Delete the runtime when finished (`agentcore destroy`, verify with `--help`).

## Observability

Structured log lines per request: `request_id`, `session`, tool name + success/error, tool-error
count, latency, and exceptions. Prompts, tool inputs, credentials and order contents are **not** logged
(only prompt length). Runtime-level logs/traces come from AgentCore's built-in CloudWatch/X-Ray integration.

## Cost precautions

- Default provider is local Ollama: development and the LLM tests cost nothing.
- Deterministic tests never call a model.
- Bedrock is only needed for the single deployment + a handful of invocations; temperature 0, short prompt, compact tool output.
- No databases, Gateway, MCP server, extra agents or other AWS services are created. Workflow mode makes no model calls at all.
- Set an AWS Budget alert, and destroy the runtime after the demo. AgentCore Runtime has its own pricing: check current pricing/credit eligibility.

## Security notes

No credentials in code; `.env` is git-ignored. Use a dedicated least-privilege execution role scoped to
the one model, logs, and image pull. Order creation is simulated; no real purchase or payment exists.

## Limitations

- Demo catalog, in-memory order/approval/execution stores (reset when the process/session ends; stock is not decremented).
- Notifications are simulated (no email is sent).
- Behaviour quality depends on the model; local small models can mis-call tools.
- Not a production procurement system.
- The deployed-runtime steps have not been executed by the author of this package (see below).

## Not implemented (possible future extensions)

MCP server, AgentCore Gateway (to expose real ERP/CRM APIs as tools), AgentCore Identity (to protect
`approve`), long-term Memory, multi-agent orchestration, async/concurrent tools, persistent execution
store (DynamoDB), real inventory/purchasing integration.
