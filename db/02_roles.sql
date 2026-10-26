-- Least-privilege read-only role for the SQL executor sandbox.
-- Runs at container init (after 01_schema.sql). Credentials are hardcoded to the
-- project defaults; if you change PG_RO_USER / PG_RO_PASSWORD in .env, update here too.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_ro') THEN
    CREATE ROLE analyst_ro LOGIN PASSWORD 'analyst_ro_pw';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE nl2sql TO analyst_ro;
GRANT USAGE ON SCHEMA shop TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA shop GRANT SELECT ON TABLES TO analyst_ro;

-- Belt and suspenders: no access to the app schema; role can never write.
REVOKE ALL ON SCHEMA app FROM analyst_ro;
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
