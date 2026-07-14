# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Archer is a multi-agent pipeline (branded "AI Investment Committee") that researches a company from a natural-language question like *"Should we invest in Stripe?"* and produces an investment memo. An orchestrator LLM call reviews the question, routes to a subset of analyst agents, they fan out in parallel via LangGraph, and a final memo agent synthesizes their output into a Presenton-generated PDF. A Next.js frontend streams live agent status over SSE, and every run is persisted to Supabase.

## Commands

Python backend is managed with **Poetry**; the frontend with **npm**.

```bash
# Install
poetry install
cd frontend && npm install && cd ..

# Run the web app (two servers)
poetry run uvicorn committee.api:app --reload --port 8000   # backend
cd frontend && npm run dev                                   # frontend on :3000, proxies /api/* → :8000

# Run the CLI (interactive prompt)
poetry run committee

# Frontend build / lint / typecheck
cd frontend && npm run build
cd frontend && npm run lint

# Python formatting / linting (dev deps)
poetry run black .        # note: line-length is 420 (see pyproject.toml)
poetry run isort .
poetry run flake8

# Tests: pytest is a dev dependency but there is no tests/ dir.
# The only test-like script is a manual harness:
poetry run python scripts/test_tavily_competitors.py
```

There is no automated test suite—`scripts/test_tavily_competitors.py` is a standalone manual check, not a pytest module.

## Architecture

The codebase splits into two Python packages plus a frontend:

- **`committee/`** — the application: agents, LangGraph wiring, FastAPI server, persistence, portfolio network.
- **`src/`** — shared infrastructure reused by the agents: `AgentState` TypedDict (`src/graph/state.py`), the `call_llm` helper (`src/utils/llm.py`), model registry (`src/llm/models.py`), and the `AgentProgress` singleton (`src/utils/progress.py`). Agents import from `src` (e.g. `from src.graph.state import AgentState`).

### Request flow (the key thing to understand)

1. `POST /api/analyze` (`committee/api.py`) → `_orchestrate()` makes a **single LLM call** that acts as a guardrail (rejects off-topic questions), extracts the company, and selects which analyst agents to run. Off-topic questions are still persisted as a `rejected` chat.
2. `build_committee(selected_agents)` (`committee/graph.py`) compiles a LangGraph with **only the selected analysts** wired from `start_node` in parallel, each going straight to `END`. `COMMITTEE_AGENTS` is the registry—add a new agent key there and it auto-joins the workflow.
3. The graph runs. Each agent calls `progress.update_status(...)` as it moves through **classify → research → synthesize → done**; a registered handler streams these as `agent_update` SSE events *and writes each agent's final JSON to `agent_outputs` the moment it finishes*.
4. **`investment_memo_agent` runs outside the graph** (called directly in `api.py` / `main.py` after `committee.invoke()`), because it needs all consolidated analyst outputs. It drafts slides and calls the Presenton API to generate the PDF.
5. The company is embedded into the portfolio network (`committee/network.py`) and its top-10 neighbours computed.
6. Everything is persisted (see below); a `complete` SSE event ends the stream.

### Agent pattern

Every analyst agent (`committee/agents/*.py`) follows the same three-step shape: **classify** (LLM extracts the subject to research), **research** (parallel Tavily web searches across multiple dimensions), **synthesize** (second LLM call → validated, range-clamped Pydantic output). All LLM calls go through `call_llm()` in `src/utils/llm.py`, which handles retries, structured output for JSON-mode models, schema injection for non-JSON models, and safe default responses on failure.

### State

`AgentState` is a `TypedDict` with `messages`, `data`, and `metadata`. `data` and `metadata` use a `merge_dicts` reducer so parallel agents can each write their slice without clobbering each other. Consolidated results end up under `state["data"]["analysis"]`.

### LLM configuration

Provider/model are env-driven via `SUMMIT_LLM_PROVIDER` (`anthropic` default, or `openai`), `SUMMIT_LLM_MODEL`, `SUMMIT_LLM_MAX_TOKENS`, and `SUMMIT_LLM_MEMO_MAX_TOKENS` (the memo uses a much larger token budget). See `get_default_model_config()` in `src/utils/llm.py`. Model metadata lives in `src/llm/api_models.json` and `src/llm/ollama_models.json`.

### Persistence (Supabase)

`committee/persistence.py` handles all reads/writes. **All persistence is fail-soft**: missing credentials or a Supabase outage never breaks a live analysis—writes are logged and skipped. Tables: `chats`, `messages`, `agent_outputs`, `decks`, `network_neighbors`, `followups`. The memo PDF is downloaded from Presenton and stored in a **public Storage bucket named `decks`** so it outlives Presenton's CDN links. Schema lives in `supabase/schema.sql` (run once in the SQL Editor). Use the **service_role** key server-side.

### Frontend

Next.js 15 (App Router) + React 19 + TypeScript in `frontend/`. `app/page.tsx` is a state machine (reducer over SSE events). `next.config.ts` rewrites `/api/*` and `/app_icon.png` to the FastAPI backend so everything is same-origin (no CORS setup). The typed API client and SSE reader live in `frontend/lib/`.

## Setup notes

- Copy `.env.example` → `.env` and fill in `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `PRESENTON_API_KEY`, and the Supabase keys. Optional debug flags: `COMMITTEE_LOG_CONSOLE=1`, `COMMITTEE_SHOW_REASONING=1`.
- `committee/network_embeddings.npy` is a cached embedding artifact; `summit_portfolio_companies.json` is the portfolio corpus embedded by `network.py` (sentence-transformers `all-MiniLM-L6-v2` + PCA).
- Watchlist decisions can schedule a follow-up rerun with a prefilled Google Calendar link—this uses Google's public event-template URL only (no OAuth, no calendar API access).
