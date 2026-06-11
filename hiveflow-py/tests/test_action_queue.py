"""Unit tests for ActionQueue: concurrency, timeout, rollback, drain."""

import asyncio

import pytest

from hiveflow.core.action_queue import ActionQueue, ActionResult, ActionStatus


async def _success_action(value: str = "ok") -> str:
    await asyncio.sleep(0.01)
    return value


async def _slow_action() -> str:
    await asyncio.sleep(10)
    return "done"


async def _failing_action() -> str:
    await asyncio.sleep(0.01)
    raise ValueError("action failed")


async def _rollback_action() -> None:
    await asyncio.sleep(0.01)


async def _failing_rollback() -> None:
    raise RuntimeError("rollback failed too")


class TestActionQueueBasic:
    """Basic submit and result tracking."""

    async def test_submit_success(self):
        queue = ActionQueue()
        result = await queue.submit("a1", _success_action, "hello")
        assert result.status == ActionStatus.COMPLETED
        assert result.result == "hello"
        assert result.started_at is not None
        assert result.completed_at is not None

    async def test_submit_returns_action_id(self):
        queue = ActionQueue()
        result = await queue.submit("my-action", _success_action)
        assert result.action_id == "my-action"

    async def test_results_accumulate(self):
        queue = ActionQueue()
        await queue.submit("a1", _success_action)
        await queue.submit("a2", _success_action)
        assert len(queue.results) == 2


class TestActionQueueTimeout:
    """Timeout enforcement."""

    async def test_timeout_marks_timed_out(self):
        queue = ActionQueue(timeout=0.05)
        result = await queue.submit("slow", _slow_action)
        assert result.status == ActionStatus.TIMED_OUT
        assert result.error is not None
        assert "timed out" in str(result.error)

    async def test_fast_action_completes_within_timeout(self):
        queue = ActionQueue(timeout=5.0)
        result = await queue.submit("fast", _success_action)
        assert result.status == ActionStatus.COMPLETED


class TestActionQueueConcurrency:
    """Concurrency control via semaphore."""

    async def test_max_concurrency_respected(self):
        max_concurrent = 0
        current_concurrent = 0

        async def tracked_action() -> str:
            nonlocal max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return "done"

        queue = ActionQueue(max_concurrency=2, timeout=5.0)
        tasks = [
            asyncio.create_task(queue.submit(f"a{i}", tracked_action))
            for i in range(6)
        ]
        await asyncio.gather(*tasks)
        assert max_concurrent <= 2


class TestActionQueueFailure:
    """Failure handling."""

    async def test_failure_marks_failed(self):
        queue = ActionQueue()
        result = await queue.submit("bad", _failing_action)
        assert result.status == ActionStatus.FAILED
        assert isinstance(result.error, ValueError)

    async def test_failure_without_rollback(self):
        queue = ActionQueue(enable_rollback=True)
        # No rollback_fn provided, so no rollback attempt
        result = await queue.submit("bad", _failing_action)
        assert result.status == ActionStatus.FAILED


class TestActionQueueRollback:
    """Rollback on failure."""

    async def test_rollback_on_failure(self):
        queue = ActionQueue(enable_rollback=True)
        result = await queue.submit(
            "bad", _failing_action, rollback_fn=_rollback_action
        )
        assert result.status == ActionStatus.ROLLED_BACK

    async def test_rollback_disabled_no_rollback(self):
        queue = ActionQueue(enable_rollback=False)
        result = await queue.submit(
            "bad", _failing_action, rollback_fn=_rollback_action
        )
        assert result.status == ActionStatus.FAILED

    async def test_rollback_failure(self):
        queue = ActionQueue(enable_rollback=True)
        result = await queue.submit(
            "bad", _failing_action, rollback_fn=_failing_rollback
        )
        assert result.status == ActionStatus.ROLLBACK_FAILED


class TestActionQueueDrain:
    """Drain semantics."""

    async def test_drain_returns_all_results(self):
        queue = ActionQueue()
        await queue.submit("a1", _success_action)
        await queue.submit("a2", _success_action)
        results = await queue.drain()
        assert len(results) == 2
        assert all(r.status == ActionStatus.COMPLETED for r in results)

    async def test_drain_empty_queue(self):
        queue = ActionQueue()
        results = await queue.drain()
        assert results == []
