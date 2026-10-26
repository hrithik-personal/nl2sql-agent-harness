"""Provision one budgeted LiteLLM virtual key per agent, and write them to .env.

Why per-agent keys (not the shared master key): the proxy then tracks spend and
enforces a budget *per agent*, and can scope each key to only the model(s) that
agent is allowed to call. That's the "model routing + token budgets + permission
scoping" story made real and visible in the admin UI (http://localhost:4000/ui).

Idempotent: any existing key with the same alias is deleted first, so re-running
always leaves exactly four keys that match .env. The proxy must be running in
DB-backed mode (DATABASE_URL set — see docker-compose.yml) or /key/* 500s.

    python scripts/provision_litellm_keys.py        # mint + rewrite .env keys

Reads LITELLM master key + base URL from the environment / .env.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# (agent, allowed models [primary + its fallback target], 30-day budget USD, env var)
SPECS = [
    ("planner", ["planner-model", "gpt-4o"], 5.0, "LITELLM_KEY_PLANNER"),
    ("verifier", ["verifier-model", "gpt-4o"], 5.0, "LITELLM_KEY_VERIFIER"),
    ("writer", ["writer-model", "gpt-4o-mini"], 2.0, "LITELLM_KEY_WRITER"),
    ("explainer", ["explainer-model", "gpt-4o-mini"], 2.0, "LITELLM_KEY_EXPLAINER"),
]


def _env(name: str, default: str = "") -> str:
    if os.getenv(name):
        return os.environ[name]
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


BASE = _env("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/")
MASTER = _env("LITELLM_MASTER_KEY", "sk-local-master")


def _api(path: str, payload: dict | None = None, method: str = "POST") -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _existing_tokens(alias: str) -> list[str]:
    try:
        d = _api("/key/list?return_full_object=true&size=100", method="GET")
    except urllib.error.HTTPError:
        return []
    rows = d.get("keys") or d.get("data") or []
    return [k["token"] for k in rows if isinstance(k, dict) and k.get("key_alias") == alias]


def _write_env(updates: dict[str, str]) -> None:
    text = ENV_PATH.read_text() if ENV_PATH.exists() else ""
    for var, val in updates.items():
        if re.search(rf"(?m)^{var}=.*$", text):
            text = re.sub(rf"(?m)^{var}=.*$", f"{var}={val}", text)
        else:
            text += ("" if text.endswith("\n") or not text else "\n") + f"{var}={val}\n"
    ENV_PATH.write_text(text)


def main() -> int:
    try:
        _api("/health/readiness", method="GET")
    except Exception as e:  # noqa: BLE001
        print(f"proxy not reachable at {BASE} ({e}); is it up in DB-backed mode?", file=sys.stderr)
        return 1

    updates: dict[str, str] = {}
    for alias, models, budget, env_var in SPECS:
        for tok in _existing_tokens(alias):  # idempotent: clear stale keys for this alias
            try:
                _api("/key/delete", {"keys": [tok]})
            except urllib.error.HTTPError:
                pass
        resp = _api(
            "/key/generate",
            {
                "key_alias": alias,
                "models": models,
                "max_budget": budget,
                "budget_duration": "30d",
                "metadata": {"agent": alias},
            },
        )
        updates[env_var] = resp["key"]
        print(f"  {alias:9s} budget=${budget:<4g} models={models}")

    _write_env(updates)
    print(f"wrote {len(updates)} virtual keys to {ENV_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
