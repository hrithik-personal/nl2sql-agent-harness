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

# real model id per agent (mirror of litellm/config.yaml) — used only for $/query
# cost estimation when the proxy doesn't echo response_cost
AGENT_REAL_MODEL = {
    "planner": "claude-sonnet-4-5",
    "verifier": "claude-sonnet-4-5",
    "writer": "claude-haiku-4-5",
    "explainer": "claude-haiku-4-5",
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


# occurrence counter per base key: the self-correction loop can issue the SAME
# prompt twice in one run (the writer re-emits identical SQL); at temperature 0 the
# model may still differ, so each occurrence needs its own cassette, replayed in order.
_occurrence: dict[str, int] = {}


def reset_cassette_counters() -> None:
    """Call at the start of each run so record and replay index identically."""
    _occurrence.clear()


def _base_digest(agent: str, model: str, messages: list[dict], schema_name: str) -> str:
    payload = json.dumps(
        {"agent": agent, "model": model, "messages": messages, "schema": schema_name},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _cassette_path(agent: str, model: str, messages: list[dict], schema_name: str) -> Path:
    """Path for the *next* occurrence of this prompt, advancing the counter."""
    digest = _base_digest(agent, model, messages, schema_name)
    idx = _occurrence.get(digest, 0)
    _occurrence[digest] = idx + 1
    return CASSETTE_DIR / f"{agent}_{digest}_{idx}.json"


def _call_litellm(agent: str, model: str, messages: list[dict]) -> LLMResponse:
    import litellm  # imported lazily so replay-mode tests need no litellm install

    s = get_settings()
    # `litellm_proxy/` routes through our LiteLLM proxy (which owns the real
    # provider/model mapping per virtual key). JSON is requested via the prompt;
    # the proxy drops response_format for providers that don't support it.
    resp = litellm.completion(
        model=f"litellm_proxy/{model}",
        messages=messages,
        api_key=_agent_key(agent),
        api_base=s.litellm_base_url,
        temperature=0,
    )
    content = resp.choices[0].message.content or "{}"
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0

    # cost: prefer the proxy's response_cost; else estimate from the real model + tokens
    cost = 0.0
    try:
        hp = getattr(resp, "_hidden_params", {}) or {}
        cost = float(hp.get("response_cost") or 0.0)
    except Exception:
        cost = 0.0
    if not cost and AGENT_REAL_MODEL.get(agent):
        try:
            pc, cc = litellm.cost_per_token(
                model=AGENT_REAL_MODEL[agent], prompt_tokens=pt, completion_tokens=ct
            )
            cost = float(pc) + float(cc)
        except Exception:
            cost = 0.0
    return LLMResponse(
        content=content,
        usage=LLMUsage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=getattr(usage, "total_tokens", 0) or (pt + ct),
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


def _extract_json(text: str) -> str:
    """Strip markdown fences / prose and return the JSON object substring."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t[3:]
        if t[:4].lower() == "json":
            t = t[4:]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t


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
        return schema.model_validate_json(_extract_json(resp.content)), resp.usage
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
        return schema.model_validate_json(_extract_json(resp2.content)), resp2.usage
