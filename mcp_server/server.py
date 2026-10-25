"""MCP server — thin adapter over the orchestrator library.

Exposes three tools with validated input schemas and the permission matrix:
  get_schema  (read)     — discover the DB structure
  ask         (read)     — full NL->answer pipeline
  run_sql     (elevated) — raw sandboxed SELECT (off unless ENABLE_RUN_SQL=1)

Transport: stdio by default; `MCP_TRANSPORT=http` serves Streamable HTTP so
remote MCP clients connect by URL with no local install.

    make mcp        # stdio
    make mcp-http   # streamable HTTP
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from nl2sql.tools.permissions import PermissionDenied, require

mcp = FastMCP("nl2sql-agent-harness")

_engine = None
_executor = None
_retriever = None


def _lazy():
    """Build heavy deps on first use (keeps import/startup cheap)."""
    global _engine, _executor, _retriever
    if _engine is None:
        from nl2sql.executor import SandboxExecutor
        from nl2sql.pipeline import build_engine
        from nl2sql.retrieve import PgVectorRetriever
        from nl2sql.telemetry import init_telemetry

        init_telemetry()
        _retriever = PgVectorRetriever()
        _engine = build_engine()
        _executor = SandboxExecutor()
    return _engine, _executor, _retriever


@mcp.tool()
def get_schema() -> dict:
    """Return the tables and columns available to query."""
    require("get_schema")
    _, _, retr = _lazy()
    return {"tables": [c.model_dump() for c in retr.cards.values()]}


@mcp.tool()
def ask(question: str, thread_id: str | None = None) -> dict:
    """Answer a natural-language question about the database."""
    require("ask")
    from nl2sql.pipeline import to_agent_result

    eng, _, _ = _lazy()
    return to_agent_result(eng.run(question, thread_id=thread_id)).model_dump()


@mcp.tool()
def ask_resume(thread_id: str, answer: str) -> dict:
    """Resume a question that paused on a clarifying question."""
    require("ask")
    from nl2sql.pipeline import to_agent_result

    eng, _, _ = _lazy()
    return to_agent_result(eng.resume(thread_id, answer)).model_dump()


@mcp.tool()
def run_sql(sql: str) -> dict:
    """Run a raw read-only SELECT through the sandbox (elevated; off by default)."""
    try:
        require("run_sql")
    except PermissionDenied as e:
        return {"error": str(e)}
    _, executor, retr = _lazy()
    return executor(sql, allowed_tables=set(retr.cards)).model_dump()


def main() -> None:
    transport = "streamable-http" if os.getenv("MCP_TRANSPORT") == "http" else "stdio"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
