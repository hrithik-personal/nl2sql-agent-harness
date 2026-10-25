#!/bin/bash
# Creates the least-privilege read-only role used by the SQL executor sandbox.
# Runs at container init (after 01_schema.sql). Reads PG_RO_USER / PG_RO_PASSWORD
# passed into the postgres container by docker-compose.
set -euo pipefail

RO_USER="${PG_RO_USER:-analyst_ro}"
RO_PASSWORD="${PG_RO_PASSWORD:-analyst_ro_pw}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${RO_USER}') THEN
      CREATE ROLE ${RO_USER} LOGIN PASSWORD '${RO_PASSWORD}';
    END IF;
  END
  \$\$;

  -- Read-only on the analytics schema only.
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${RO_USER};
  GRANT USAGE ON SCHEMA shop TO ${RO_USER};
  GRANT SELECT ON ALL TABLES IN SCHEMA shop TO ${RO_USER};
  ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT SELECT ON TABLES TO ${RO_USER};

  -- Belt and suspenders: no access to our app schema, and make the role
  -- itself incapable of writing anywhere.
  REVOKE ALL ON SCHEMA app FROM ${RO_USER};
  ALTER ROLE ${RO_USER} SET default_transaction_read_only = on;
EOSQL

echo "role ${RO_USER} created with read-only grants on schema shop"
