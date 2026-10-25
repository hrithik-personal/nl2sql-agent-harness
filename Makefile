.PHONY: help venv up down seed index api run mcp eval test lint fmt

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n",$$1,$$2}'

venv: ## create venv and install the package (public PyPI)
	python3 -m venv .venv
	$(PIP) install --index-url https://pypi.org/simple/ -e ".[dev]"

up: ## start Postgres + LiteLLM + Phoenix
	docker compose up -d

down: ## stop services
	docker compose down

seed: ## load deterministic Faker data into the shop schema
	$(PY) -m db.seed

index: ## build schema-card + exemplar embeddings into pgvector
	$(PY) -m nl2sql.indexing

api: ## run FastAPI (http://localhost:8000)
	.venv/bin/uvicorn api.main:app --reload --port 8000

run: ## run the Streamlit UI (http://localhost:8501)
	.venv/bin/streamlit run app/streamlit_app.py

mcp: ## run the MCP server over stdio
	$(PY) -m mcp_server.server

mcp-http: ## run the MCP server over Streamable HTTP
	MCP_TRANSPORT=http $(PY) -m mcp_server.server

eval: ## run the eval harness (cassette replay) -> scorecard
	LLM_MODE=replay $(PY) -m evals.run_evals

test: ## unit + cassette-replayed tests
	LLM_MODE=replay $(PY) -m pytest -q

lint: ## ruff
	.venv/bin/ruff check .

fmt: ## ruff format
	.venv/bin/ruff format .
