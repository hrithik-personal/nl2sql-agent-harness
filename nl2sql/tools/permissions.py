"""Tool permission matrix (least privilege).

    get_schema : read     — safe, always on (discovery)
    ask        : read     — safe default (full pipeline, sandboxed execution)
    run_sql    : elevated — raw read-only SELECT; OFF by default, opt in with
                            ENABLE_RUN_SQL=1 (and per-client auth on MCP-HTTP)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPermission:
    scope: str  # "read" | "elevated"
    default_enabled: bool


MATRIX: dict[str, ToolPermission] = {
    "get_schema": ToolPermission("read", True),
    "ask": ToolPermission("read", True),
    "run_sql": ToolPermission("elevated", False),
}


def is_enabled(tool: str) -> bool:
    perm = MATRIX.get(tool)
    if perm is None:
        return False
    if tool == "run_sql":
        return os.getenv("ENABLE_RUN_SQL", "0") == "1"
    return perm.default_enabled


class PermissionDenied(Exception):
    pass


def require(tool: str) -> None:
    if not is_enabled(tool):
        raise PermissionDenied(
            f"tool '{tool}' is disabled by the permission matrix "
            f"(scope={MATRIX.get(tool).scope if tool in MATRIX else 'unknown'})"
        )
