"""Async operation scopes for explicitly exposed owner capabilities."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial, wraps
from typing import Self

from .concurrency import JoinedOperations


class ServiceScopeClosedError(Exception):
    """An operation view cannot escape its explicit lifetime."""


@asynccontextmanager
async def _local_scope() -> AsyncIterator[None]:
    yield


class ServiceScope:
    """Admission surrounds the entire owner call, including deferred cleanup."""

    def __init__(self, lease: Callable[[], AbstractAsyncContextManager[None]] = _local_scope,
                 operations: JoinedOperations | None = None) -> None:
        self._lease = lease
        self._operations = operations

    def using(self, operations: JoinedOperations) -> ServiceScope:
        return ServiceScope(self._lease, operations)

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[ServiceScope]:
        async with self._lease():
            active = True

            @asynccontextmanager
            async def entered() -> AsyncIterator[None]:
                if not active:
                    raise ServiceScopeClosedError("Service operation scope is closed")
                yield

            operations = self._operations or JoinedOperations()
            try:
                yield ServiceScope(entered, operations)
            finally:
                active = False
            if self._operations is None:
                operations.check_cancelled()

    def local[**P, R](self, operation: Callable[P, R]) -> Callable[P, Awaitable[R]]:
        @wraps(operation)
        async def run(*args: P.args, **kwargs: P.kwargs) -> R:
            async with self._lease():
                joined = self._operations or JoinedOperations()
                result = await joined.run(partial(operation, *args, **kwargs))
                if self._operations is None:
                    joined.check_cancelled()
                return result
        return run

    def remote[**P, R](self, operation: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(operation)
        async def run(*args: P.args, **kwargs: P.kwargs) -> R:
            async with self._lease():
                return await operation(*args, **kwargs)
        return run


class ScopedService[T]:
    """Private owner plus explicit operations; no generic public owner access."""

    def __init__(self, owner: T, scope: ServiceScope = ServiceScope()) -> None:
        self._owner = owner
        self._scope = scope

    def using(self, operations: JoinedOperations) -> Self:
        """Let an Action record completed facts before honoring cancellation."""
        return type(self)(self._owner, self._scope.using(operations))

    def _bind(self, scope: ServiceScope) -> Self:
        return type(self)(self._owner, scope)

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[Self]:
        """Hold one admission boundary across a compound owner operation."""
        async with self._scope.operation() as scope:
            yield self._bind(scope)
