-- Run as the target database owner AFTER attaching Lakebase to the new app.
-- Replace only the string below with the NEW app's service principal CLIENT ID.
-- The Lakebase App resource creates the corresponding PostgreSQL role.
DO $$
DECLARE
  app_role text := 'REPLACE_WITH_NEW_APP_SERVICE_PRINCIPAL_CLIENT_ID';
BEGIN
  IF app_role !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' THEN
    RAISE EXCEPTION 'Replace app_role with the new app service principal client ID.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
    RAISE EXCEPTION 'App role is missing. Attach the target Lakebase database to the new app first.';
  END IF;
  EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.atlas_users, public.atlas_conversations, public.atlas_messages, public.atlas_comments, public.atlas_tool_runs TO %I', app_role);
END;
$$;
