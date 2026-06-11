"""Action Queue - Controlled execution of side-effect actions.

Provides concurrency control, timeout enforcement, and rollback support
for side-effect actions in workflows.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ActionStatus(StrEnum):
    """Lifecycle states for a queued action."""

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


@dataclass
class ActionResult:
    """Result of an action execution."""

    action_id: str
    status: ActionStatus
    result: Any = None
    error: Exception | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ActionQueue:
    """Queue for side-effect actions with concurrency control and timeout.

    Uses asyncio.Semaphore for concurrency limiting and asyncio.wait_for
    for timeout enforcement. Supports rollback on failure.

    Example:
        queue = ActionQueue(max_concurrency=5, timeout=30.0)
        result = await queue.submit("send_email", send_email_fn, args)
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        timeout: float = 30.0,
        enable_rollback: bool = False,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
        self._enable_rollback = enable_rollback
        self._results: list[ActionResult] = []
        self._pending: list[asyncio.Task[ActionResult]] = []

    async def submit(
        self,
        action_id: str,
        action_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        rollback_fn: Callable[..., Coroutine[Any, Any, Any]] | None = None,
        **kwargs: Any,
    ) -> ActionResult:
        """Submit an action for execution.

        Blocks until a concurrency slot is available, then executes with
        timeout. Triggers rollback on failure if enabled and rollback_fn provided.

        Args:
            action_id: Unique identifier for this action
            action_fn: Async callable to execute
            *args: Positional arguments for action_fn
            rollback_fn: Optional async callable for rollback on failure
            **kwargs: Keyword arguments for action_fn

        Returns:
            ActionResult with status and outcome
        """
        async with self._semaphore:
            result = ActionResult(
                action_id=action_id,
                status=ActionStatus.EXECUTING,
                started_at=datetime.now(UTC),
            )

            try:
                outcome = await asyncio.wait_for(
                    action_fn(*args, **kwargs),
                    timeout=self._timeout,
                )
                result.status = ActionStatus.COMPLETED
                result.result = outcome

            except TimeoutError:
                result.status = ActionStatus.TIMED_OUT
                result.error = TimeoutError(f"Action {action_id} timed out after {self._timeout}s")
                logger.warning("Action %s timed out after %.1fs", action_id, self._timeout)

            except Exception as exc:
                result.status = ActionStatus.FAILED
                result.error = exc
                logger.warning("Action %s failed: %s", action_id, exc)

                # Attempt rollback if enabled and rollback function provided
                if self._enable_rollback and rollback_fn is not None:
                    result = await self._execute_rollback(result, rollback_fn)

            finally:
                result.completed_at = datetime.now(UTC)
                self._results.append(result)

        return result

    async def _execute_rollback(
        self,
        result: ActionResult,
        rollback_fn: Callable[..., Coroutine[Any, Any, Any]],
    ) -> ActionResult:
        """Attempt to rollback a failed action."""
        result.status = ActionStatus.ROLLING_BACK
        logger.info("Rolling back action %s", result.action_id)

        try:
            await asyncio.wait_for(rollback_fn(), timeout=self._timeout)
            result.status = ActionStatus.ROLLED_BACK
            logger.info("Rollback succeeded for action %s", result.action_id)
        except Exception as rollback_exc:
            result.status = ActionStatus.ROLLBACK_FAILED
            logger.error("Rollback failed for action %s: %s", result.action_id, rollback_exc)

        return result

    async def drain(self) -> list[ActionResult]:
        """Wait for all pending tasks and return all results.

        Returns:
            List of all ActionResults from submitted actions
        """
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
            self._pending.clear()
        return list(self._results)

    @property
    def results(self) -> list[ActionResult]:
        """All action results collected so far."""
        return list(self._results)
