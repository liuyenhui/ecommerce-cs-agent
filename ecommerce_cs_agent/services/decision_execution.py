from __future__ import annotations

from functools import partial
from typing import Callable, TypeVar

import anyio


T = TypeVar("T")


class BoundedDecisionExecutor:
    """Runs synchronous decision work off the event loop with bounded concurrency."""

    def __init__(self, *, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        self._limiter = anyio.CapacityLimiter(max_concurrency)

    async def run(
        self,
        operation: Callable[..., T],
        /,
        *args: object,
        **kwargs: object,
    ) -> T:
        call = partial(operation, *args, **kwargs)
        return await anyio.to_thread.run_sync(call, limiter=self._limiter)
