"""Validated tool input schemas.

Every tool exposed over MCP / HTTP has a strict Pydantic input contract, so
malformed calls are rejected before any agent or SQL runs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = None


class ResumeInput(BaseModel):
    thread_id: str = Field(min_length=1)
    answer: str = Field(min_length=1, max_length=2000)


class RunSqlInput(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)


class GetSchemaInput(BaseModel):
    pass
