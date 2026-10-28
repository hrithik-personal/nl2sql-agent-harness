"""Record/replay layer for the retrieval step — the twin of nl2sql/llm.py.

Retrieval ranks tables with embeddings + pgvector, which is *machine-sensitive*:
tiny floating-point differences across CPUs can reorder near-ties, and a reordered
context changes every downstream prompt. The eval/replay path relies on
byte-identical prompts (that's how the LLM cassettes match), so we freeze the
retrieved context once with LLM_MODE=record and serve it verbatim on LLM_MODE=replay.

Result: offline runs (tests, evals, CI) are deterministic on *any* machine, and
need neither the embedding model nor pgvector at replay time.

LLM_MODE (shared with the LLM layer):
  live    -> call the real retriever; no fixture
  record  -> call the real retriever AND persist the context as a fixture
  replay  -> load the fixture only (a miss is a hard error)
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from nl2sql.config import get_settings
from nl2sql.schemas import RetrievedContext

RETRIEVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "cassettes" / "retrieval"


def _key(question: str) -> str:
    return hashlib.sha256(question.strip().encode()).hexdigest()[:24]


class RetrievalCassette:
    """Wrap a retriever with LLM_MODE-driven record/replay.

    The inner retriever is built lazily via `inner_factory`, so a pure replay run
    never constructs it (no DB introspection, no embedding model loaded).
    """

    def __init__(self, inner_factory: Callable[[], Callable[[str], RetrievedContext]]) -> None:
        self._inner_factory = inner_factory
        self._inner: Callable[[str], RetrievedContext] | None = None

    def _inner_retriever(self) -> Callable[[str], RetrievedContext]:
        if self._inner is None:
            self._inner = self._inner_factory()
        return self._inner

    def __call__(self, question: str) -> RetrievedContext:
        mode = get_settings().llm_mode.lower()
        path = RETRIEVAL_DIR / f"{_key(question)}.json"

        if mode == "replay":
            if not path.exists():
                raise RuntimeError(
                    f"retrieval cassette miss in replay mode: {path.name} "
                    f"(question={question!r}). Re-record with LLM_MODE=record."
                )
            return RetrievedContext.model_validate_json(path.read_text())

        ctx = self._inner_retriever()(question)
        if mode == "record":
            RETRIEVAL_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(ctx.model_dump_json(indent=2))
        return ctx
