"""Single choke point for every LLM call.

- Routes through the LiteLLM proxy using a per-agent virtual key (so the proxy
  owns model routing, budgets and rate limits — see litellm/config.yaml).
- Enforces structured outputs against a Pydantic schema.
- Wraps a cassette record/replay layer so tests, evals and CI run offline,
  deterministically, with no API key and no proxy.

LLM_MODE:
  live    -> call the real model; ignore cassettes
  record  -> call the real model AND persist the exchange as a cassette
  replay  -> never call out; serve from cassettes (a miss is a hard error)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from nl2sql.config import get_settings

T = TypeVar("T", bound=BaseModel)

CASSETTE_DIR = Path(__file__).resolve().parent.parent / "tests" / "cassettes"

# logical model alias per agent; the LiteLLM proxy maps alias+key -> real model
AGENT_MODEL = {
    "planner": "planner-model",
    "writer": "writer-model",
    "verifier": "verifier-model",
    "explainer": "explainer-model",
}


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class LLMResponse(BaseModel):
    content: str
    usage: LLMUsage = LLMUsage()


def _agent_key(agent: str) -> str:
    s = get_settings()
    return {
        "planner": s.litellm_key_planner,
        "writer": s.litellm_key_writer,
        "verifier": s.litellm_key_verifier,
        "explainer": s.litellm_key_explainer,
    }.get(agent, s.litellm_key_planner)


def _cassette_path(agent: str, model: str, messages: list[dict], schema_name: str) -> Path:
    payload = json.dumps(
        {"agent": agent, "model": model, "messages": messages, "schema": schema_name},
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return CASSETTE_DIR / f"{agent}_{digest}.json"


def _call_litellm(agent: str, model: str, messages: list[dict]) -> LLMResponse:
    import litellm  # imported lazily so replay-mode tests need no litellm install

    s = get_settings()
    resp = litellm.completion(
        model=model,
        messages=messages,
        api_key=_agent_key(agent),
        base_url=s.litellm_base_url,
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        cost = float(litellm.completion_cost(completion_response=resp))
    except Exception:
        cost = 0.0
    usage = getattr(resp, "usage", None)
    return LLMResponse(
        content=content,
        usage=LLMUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            cost_usd=cost,
        ),
    )


def _raw_complete(agent: str, messages: list[dict], schema_name: str) -> LLMResponse:
    s = get_settings()
    model = AGENT_MODEL.get(agent, "planner-model")
    mode = s.llm_mode.lower()

    if mode == "replay":
        path = _cassette_path(agent, model, messages, schema_name)
        if not path.exists():
            raise RuntimeError(
                f"cassette miss in replay mode: {path.name} "
                f"(agent={agent}). Re-record with LLM_MODE=record."
            )
        data = json.loads(path.read_text())
        return LLMResponse(**data)

    resp = _call_litellm(agent, model, messages)

    if mode == "record":
        CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cassette_path(agent, model, messages, schema_name)
        path.write_text(json.dumps(resp.model_dump(), indent=2, sort_keys=True))

    return resp


def complete_structured(
    agent: str,
    system: str,
    user: str,
    schema: type[T],
) -> tuple[T, LLMUsage]:
    """Call `agent`'s model and parse the reply into `schema`.

    The JSON schema is embedded in the system prompt; one repair attempt is made
    if the first reply fails validation.
    """
    schema_json = json.dumps(schema.model_json_schema())
    sys_full = (
        f"{system}\n\nReply with a single JSON object that validates against this "
        f"JSON Schema. No prose, no markdown fences.\nSCHEMA:\n{schema_json}"
    )
    messages = [{"role": "system", "content": sys_full}, {"role": "user", "content": user}]

    resp = _raw_complete(agent, messages, schema.__name__)
    try:
        return schema.model_validate_json(resp.content), resp.usage
    except (ValidationError, ValueError):
        # one repair round-trip
        repair = messages + [
            {"role": "assistant", "content": resp.content},
            {
                "role": "user",
                "content": "That did not validate against the schema. Return ONLY valid JSON.",
            },
        ]
        resp2 = _raw_complete(agent, repair, schema.__name__)
        return schema.model_validate_json(resp2.content), resp2.usage
