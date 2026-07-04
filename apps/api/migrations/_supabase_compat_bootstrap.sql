-- Supabase-compatibility bootstrap for running the migration set against a
-- plain PostgreSQL instance (local dev / CI schema harness).
--
-- Production runs on hosted Supabase, which pre-provisions the auth/storage
-- schemas, the anon/authenticated/service_role roles, and the auth.uid()/
-- auth.jwt()/auth.role() helpers that RLS policies reference. A vanilla
-- Postgres has none of these, so applying the migrations there fails on the
-- first GRANT ... TO authenticated or auth.uid() reference.
--
-- This file stands up the minimum Supabase surface the migrations depend on so
-- the full DDL (tables, columns, constraints, triggers, RLS policies) can be
-- created and asserted against. It is NOT applied to production (Supabase
-- already provides all of this) — the migration runner injects it only when
-- --with-compat is passed.

-- Extensions used by the schema (gen_random_uuid, pgcrypto).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Supabase roles referenced by GRANT / RLS TO clauses.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
    CREATE ROLE authenticator NOINHERIT LOGIN;
  END IF;
END
$$;

GRANT anon, authenticated, service_role TO authenticator;

-- Supabase-managed schemas.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS storage;
CREATE SCHEMA IF NOT EXISTS extensions;

-- auth.users — RLS policies and some FKs reference it. Minimal shape.
CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text
);

-- storage.buckets / storage.objects — a couple of migrations reference the
-- Supabase Storage catalog (bucket provisioning, RLS on objects). Minimal shape.
CREATE TABLE IF NOT EXISTS storage.buckets (
  id text PRIMARY KEY,
  name text NOT NULL,
  public boolean DEFAULT false
);
CREATE TABLE IF NOT EXISTS storage.objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_id text REFERENCES storage.buckets(id),
  name text,
  owner uuid
);

-- Supabase JWT/session helpers. On real Supabase these read the request JWT
-- via current_setting('request.jwt.claims'). The stubs below reproduce that
-- behaviour so RLS predicates using auth.uid()/auth.jwt()->>'...' parse and
-- evaluate (returning NULL when no claims are set, i.e. deny-by-default).
CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS jsonb
LANGUAGE sql STABLE
AS $$
  SELECT coalesce(
    nullif(current_setting('request.jwt.claims', true), ''),
    '{}'
  )::jsonb
$$;

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql STABLE
AS $$
  SELECT nullif(auth.jwt() ->> 'sub', '')::uuid
$$;

CREATE OR REPLACE FUNCTION auth.role()
RETURNS text
LANGUAGE sql STABLE
AS $$
  SELECT coalesce(auth.jwt() ->> 'role', current_setting('request.jwt.claim.role', true))
$$;

CREATE OR REPLACE FUNCTION auth.email()
RETURNS text
LANGUAGE sql STABLE
AS $$
  SELECT auth.jwt() ->> 'email'
$$;

-- storage.foldername() — used by Storage RLS policies to scope objects by path.
CREATE OR REPLACE FUNCTION storage.foldername(name text)
RETURNS text[]
LANGUAGE sql IMMUTABLE
AS $$
  SELECT string_to_array(name, '/')
$$;

GRANT USAGE ON SCHEMA auth, storage, extensions TO anon, authenticated, service_role;
