"""Remove native ChatLog payloads without modifying HA tool execution."""

import logging
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from functools import wraps
from typing import Any

_PRIVATE: ContextVar[bool] = ContextVar("deepseek_ai_private_request", default=False)

_LOGGERS = [
    logging.getLogger("homeassistant.components.conversation." + name)
    for name in ("chat_log", "agent_manager")
]


class PayloadFilter(logging.Filter):
    """ChatLog logs before entity hooks, so filtering must cover its logger."""

    users = 0

    def filter(self, record: logging.LogRecord) -> bool:
        # ChatLog's debug records contain raw prompts, deltas and tool results.
        # Its rendering/API error records can contain user templates too.
        if record.levelno > logging.DEBUG and not _PRIVATE.get():
            return True
        record.msg = "ChatLog payload omitted by DeepSeek AI privacy filter"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


_FILTER = PayloadFilter()


def install() -> Callable[[], None]:
    if not _FILTER.users:
        for logger in _LOGGERS:
            logger.addFilter(_FILTER)
    _FILTER.users += 1

    def remove() -> None:
        _FILTER.users -= 1
        if not _FILTER.users:
            for logger in _LOGGERS:
                logger.removeFilter(_FILTER)

    return remove


def private_request[**P, T](
    function: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Scope error redaction to this integration, including HA tool subtasks."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        token = _PRIVATE.set(True)
        try:
            return await function(*args, **kwargs)
        finally:
            _PRIVATE.reset(token)

    return wrapped
