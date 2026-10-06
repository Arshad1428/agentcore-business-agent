"""Session cache and execution store tests. No LLM, no AWS."""
from business_agent.executions import ExecutionStore, SessionCache


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def test_session_reused_within_ttl():
    clock, made = Clock(), []
    cache = SessionCache(lambda: made.append(object()) or made[-1], 10, 100, clock)
    a = cache.get("s1"); clock.t = 50
    assert cache.get("s1") is a and len(made) == 1


def test_session_expires_after_idle_ttl():
    clock = Clock()
    cache = SessionCache(object, 10, 100, clock)
    a = cache.get("s1"); clock.t = 101
    assert cache.get("s1") is not a


def test_lru_eviction_caps_sessions():
    cache = SessionCache(object, max_sessions=2, ttl_seconds=1000, clock=Clock())
    cache.get("a"); cache.get("b"); cache.get("a"); cache.get("c")  # b is least recently used
    assert len(cache) == 2 and "b" not in cache and "a" in cache and "c" in cache


def test_execution_lifecycle():
    store = ExecutionStore()
    eid = store.start("workflow", "s1", "purchase_order")
    assert store.get(eid)["status"] == "running"
    store.finish(eid, "completed", latency_ms=5)
    rec = store.get(eid)
    assert rec["status"] == "completed" and rec["finished_at"] and rec["latency_ms"] == 5


def test_execution_store_is_bounded_and_filters_by_session():
    store = ExecutionStore(max_records=3)
    ids = [store.start("agent", "s1" if i % 2 == 0 else "s2") for i in range(5)]
    assert store.get(ids[0]) is None and store.get(ids[4]) is not None
    assert all(r["session_id"] == "s1" for r in store.list(session_id="s1"))
    assert store.get("exe-unknown") is None
