"""Seed the portfolio_companies table from summit_portfolio_companies.json.

Each company's id is its INDEX in the JSON array — the same integer
committee/network.py emits as a neighbour's id (network_neighbors.neighbor_id),
so the foreign key lines up. Upserts on id, so re-running is idempotent.

Usage (from ai-investment-team):

    poetry run python scripts/seed_portfolio_companies.py

Requires SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env, and the
portfolio_companies table created (see supabase/schema.sql).
"""

import json
import os
import sys

from dotenv import load_dotenv

here = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(here)
project_root = os.path.dirname(repo_root)

load_dotenv(os.path.join(repo_root, ".env"))
load_dotenv(os.path.join(project_root, ".env"), override=True)

sys.path.insert(0, repo_root)

from committee.persistence import get_supabase_client, upsert_portfolio_companies  # noqa: E402

JSON_PATH = os.path.join(repo_root, "summit_portfolio_companies.json")


def main() -> int:
    with open(JSON_PATH) as f:
        companies = json.load(f)
    print(f"Loaded {len(companies)} companies from {os.path.basename(JSON_PATH)}")

    if get_supabase_client() is None:
        print(
            "Supabase is not configured (set SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY "
            "in .env). Nothing was written.",
            file=sys.stderr,
        )
        return 1

    written = upsert_portfolio_companies(companies)
    if written == 0:
        print("No rows written — check the logs above for the Supabase error.", file=sys.stderr)
        return 1

    print(f"Upserted {written} rows into portfolio_companies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
