-- Memory feature: chat/agent-output/deck/network persistence.
-- Run this once in the Supabase SQL Editor for a fresh project.
-- After running, create a public Storage bucket named "decks" (Storage -> New bucket -> Public: ON).

create extension if not exists "pgcrypto"; -- for gen_random_uuid()

create table if not exists chats (
  id uuid primary key default gen_random_uuid(),
  title text,
  company text,
  question text not null,
  status text not null default 'running'
    check (status in ('running', 'done', 'rejected', 'error')),
  analysis jsonb,
  network_snapshot jsonb,
  synthesis jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists chats_created_at_idx on chats (created_at desc);
-- If the chats table already exists, add the synthesis column:
--   alter table chats add column if not exists synthesis jsonb;

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists messages_chat_id_idx on messages (chat_id);

create table if not exists decks (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  storage_path text not null,
  public_url text not null,
  edit_path text,
  file_name text,
  content_type text default 'application/pdf',
  file_size_bytes bigint,
  created_at timestamptz not null default now()
);
create index if not exists decks_chat_id_idx on decks (chat_id);

-- One row per agent per chat, written the moment that agent finishes (not
-- just once at the end of the whole run) — the raw verbose JSON each agent
-- produces (market_analyzer, founder_analyzer, product_analyst,
-- competitive_intelligence, investment_memo), independent of the
-- consolidated copy already nested in chats.analysis.
create table if not exists agent_outputs (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  agent_name text not null,
  ticker text,
  output jsonb not null,
  created_at timestamptz not null default now(),
  unique (chat_id, agent_name)
);
create index if not exists agent_outputs_chat_id_idx on agent_outputs (chat_id);

-- One row per portfolio neighbour in the top-10 similarity ranking for a
-- given analysis, alongside the compact copy already nested in
-- chats.network_snapshot — lets you query neighbour relationships directly
-- (e.g. "which analyses had Airtable in the top 10", "avg similarity for
-- Notion's neighbours") instead of unpacking JSON.
create table if not exists network_neighbors (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  company text not null,
  rank smallint not null,
  neighbor_id integer not null,
  neighbor_name text not null,
  neighbor_sector text,
  similarity double precision not null,
  x double precision,
  y double precision,
  created_at timestamptz not null default now(),
  unique (chat_id, neighbor_id)
);
create index if not exists network_neighbors_chat_id_idx on network_neighbors (chat_id);
create index if not exists network_neighbors_company_idx on network_neighbors (company);

-- Scheduled reruns for watchlist decisions. When the committee returns
-- "watchlist", the user can schedule a follow-up: the due date lives here
-- (the Google Calendar event is just their personal reminder — the app
-- prompts from this table), and the rerun only happens after the user
-- approves it in the UI. rerun_chat_id links the fresh analysis chat back
-- to the original watchlist chat.
create table if not exists followups (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  company text not null,
  question text not null,
  due_date date not null,
  status text not null default 'pending'
    check (status in ('pending', 'done', 'dismissed')),
  rerun_chat_id uuid references chats(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists followups_status_due_idx on followups (status, due_date);
