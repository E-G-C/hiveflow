"""Example: ActionQueue — Concurrency Control, Timeout, and Rollback.

Demonstrates how to:
1. Submit async actions with concurrency limiting
2. Enforce timeouts on slow actions
3. Handle rollback on failure
4. Drain all results

No live LLM needed — uses async simulations.

Usage:
    uv run python examples/config_operations/05_action_queue.py
"""

import asyncio

from hiveflow.core.action_queue import ActionQueue, ActionStatus


async def send_notification(recipient: str) -> dict[str, str]:
    """Simulated action: send a notification."""
    await asyncio.sleep(0.1)
    return {"status": "sent", "to": recipient}


async def slow_database_update() -> dict[str, str]:
    """Simulated action that takes too long."""
    await asyncio.sleep(10)  # Will be killed by timeout
    return {"status": "updated"}


async def deploy_service() -> dict[str, str]:
    """Simulated action that fails."""
    await asyncio.sleep(0.05)
    raise RuntimeError("Deployment failed: health check timeout")


async def rollback_deployment() -> None:
    """Rollback action for failed deployment."""
    await asyncio.sleep(0.05)
    print("    [rollback] Previous version restored")


async def main() -> None:
    # -- 1. Basic concurrent actions -------------------------------------------
    print("--- 1. Concurrent action execution ---")
    queue = ActionQueue(max_concurrency=3, timeout=5.0)

    recipients = ["alice@example.com", "bob@example.com", "carol@example.com",
                   "dave@example.com", "eve@example.com"]

    tasks = [
        asyncio.create_task(queue.submit(f"notify-{r.split('@')[0]}", send_notification, r))
        for r in recipients
    ]
    results = await asyncio.gather(*tasks)

    for r in results:
        print(f"  {r.action_id}: {r.status.value} -> {r.result}")
    print(f"  Total: {len(results)} actions, max_concurrency=3")

    # -- 2. Timeout enforcement ------------------------------------------------
    print("\n--- 2. Timeout enforcement ---")
    queue = ActionQueue(max_concurrency=1, timeout=0.2)
    result = await queue.submit("db-update", slow_database_update)
    print(f"  {result.action_id}: {result.status.value}")
    print(f"  Error: {result.error}")

    # -- 3. Failure without rollback -------------------------------------------
    print("\n--- 3. Failure without rollback ---")
    queue = ActionQueue(max_concurrency=1, timeout=5.0, enable_rollback=False)
    result = await queue.submit("deploy-v2", deploy_service)
    print(f"  {result.action_id}: {result.status.value}")
    print(f"  Error: {result.error}")

    # -- 4. Failure with rollback ----------------------------------------------
    print("\n--- 4. Failure with rollback ---")
    queue = ActionQueue(max_concurrency=1, timeout=5.0, enable_rollback=True)
    result = await queue.submit(
        "deploy-v3", deploy_service, rollback_fn=rollback_deployment
    )
    print(f"  {result.action_id}: {result.status.value}")

    # -- 5. Drain all results --------------------------------------------------
    print("\n--- 5. Drain pattern ---")
    queue = ActionQueue(max_concurrency=2, timeout=5.0)
    await queue.submit("action-a", send_notification, "a@test.com")
    await queue.submit("action-b", send_notification, "b@test.com")
    await queue.submit("action-c", send_notification, "c@test.com")

    all_results = await queue.drain()
    print(f"  Drained: {len(all_results)} results")
    for r in all_results:
        print(f"    {r.action_id}: {r.status.value}")

    # -- 6. Integration with config defaults -----------------------------------
    print("\n--- 6. Config-driven defaults ---")
    from hiveflow.core.config import HiveFlowConfig
    config = HiveFlowConfig()
    print(f"  DEFAULT_ACTION_POLICY: {config.DEFAULT_ACTION_POLICY}")
    print(f"  ENABLE_ROLLBACK:      {config.ENABLE_ROLLBACK}")
    print(f"  ACTION_TIMEOUT:       {config.ACTION_TIMEOUT}s")
    print("  (These defaults are used by the action executor agent behavior)")


if __name__ == "__main__":
    asyncio.run(main())
