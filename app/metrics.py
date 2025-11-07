from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List

_MAX = 200
_query_history: Deque[Dict[str, Any]] = deque(maxlen=_MAX)


def log_query_stat(stat: Dict[str, Any]) -> None:
    _query_history.appendleft(stat)


def get_query_stats() -> List[Dict[str, Any]]:
    return list(_query_history)

