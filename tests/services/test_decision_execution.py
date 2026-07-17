from __future__ import annotations

import threading
import time

import anyio

from ecommerce_cs_agent.services.decision_execution import BoundedDecisionExecutor


def test_executor_runs_blocking_work_outside_event_loop_thread() -> None:
    async def exercise() -> None:
        event_loop_thread_id = threading.get_ident()
        executor = BoundedDecisionExecutor(max_concurrency=2)

        worker_thread_id = await executor.run(threading.get_ident)

        assert worker_thread_id != event_loop_thread_id

    anyio.run(exercise)


def test_executor_never_exceeds_configured_concurrency() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def blocking_operation() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
        finally:
            with lock:
                active -= 1

    async def exercise() -> None:
        executor = BoundedDecisionExecutor(max_concurrency=2)
        async with anyio.create_task_group() as task_group:
            for _ in range(8):
                task_group.start_soon(executor.run, blocking_operation)

    anyio.run(exercise)

    assert peak == 2


def test_executor_rejects_non_positive_concurrency() -> None:
    for value in (0, -1):
        try:
            BoundedDecisionExecutor(max_concurrency=value)
        except ValueError as exc:
            assert str(exc) == "max_concurrency must be a positive integer"
        else:
            raise AssertionError(f"expected max_concurrency={value} to be rejected")
