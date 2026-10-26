-- Separate database for the LiteLLM proxy's own state (virtual keys, budgets,
-- spend, users). Kept apart from `nl2sql` so LiteLLM's Prisma migrations never
-- touch our shop/app schemas. Owned by the app user, which is how the proxy
-- connects (see DATABASE_URL in docker-compose.yml).
-- Runs once at first init; CREATE DATABASE can't be IF NOT EXISTS, so for an
-- already-initialised volume this is applied manually (see Makefile: litellm-db).
CREATE DATABASE litellm OWNER nl2sql_app;
