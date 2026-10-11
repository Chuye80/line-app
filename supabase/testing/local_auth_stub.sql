-- Minimal stand-in for the pieces of Supabase's `auth` schema that the
-- migrations reference. Used only by the local test harness so that the real
-- migration files can be executed unmodified against a plain PostgreSQL
-- instance. This file is never applied to a Supabase project.

create schema if not exists auth;

create table if not exists auth.users (
    id uuid primary key default gen_random_uuid(),
    email text unique,
    raw_user_meta_data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
