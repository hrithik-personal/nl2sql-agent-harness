.PHONY: help venv up down seed index api run mcp eval test lint fmt litellm-db litellm-keys

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

litellm-db: ## create the `litellm` database (only needed on a pre-existing pg volume)
	docker compose exec -T postgres psql -U $${PG_APP_USER:-nl2sql_app} -d $${PG_DB:-nl2sql} \
	  -tc "SELECT 1 FROM pg_database WHERE datname='litellm'" | grep -q 1 \
	  || docker compose exec -T postgres psql -U $${PG_APP_USER:-nl2sql_app} -d $${PG_DB:-nl2sql} \
	       -c "CREATE DATABASE litellm OWNER $${PG_APP_USER:-nl2sql_app};"

litellm-keys: ## mint 1 budgeted virtual key per agent + write them to .env
	$(PY) scripts/provision_litellm_keys.py

eval: ## run the eval harness (cassette replay) -> scorecard
	LLM_MODE=replay $(PY) -m evals.run_evals

test: ## unit + cassette-replayed tests
	LLM_MODE=replay $(PY) -m pytest -q

lint: ## ruff
	.venv/bin/ruff check .

fmt: ## ruff format
	.venv/bin/ruff format .
