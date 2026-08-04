#!/usr/bin/env python3
"""
Seed Supabase from a clients JSON file.

Usage:
  export SUPABASE_URL="https://your-project.supabase.co"
  export SUPABASE_KEY="your-anon-or-service-role-key"
  python scripts/seed_supabase.py [--json data/configs/clients.json]

Accepts either shape of ``clients.json``:

* **counters** (current) — each client carries its serving lines inline::

      {"clients": [{"name": "Amadeus",
                    "city": "Bangalore",
                    "serve_weekends": false,
                    "item_cooldown_days": 20,
                    "source_pools": ["amadeus"],
                    "counters": [{"name": "South",
                                  "categories": [...],
                                  "slot_counts": {...},
                                  "theme_map": {...}}]}]}

* **legacy** — ``menu_category`` + the ``menu_categories`` /
  ``slot_count_overrides`` / ``theme_overrides`` maps, which are folded
  into a single "Counter 1" per client on the way in.

This script is idempotent — it upserts, so re-running is safe.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from supabase import create_client

DEFAULT_COUNTER_NAME = "Counter 1"


def _counters_from_legacy(client, data):
    """Fold the legacy side-maps into a one-counter list for *client*."""
    name = client["name"]
    categories = data.get("menu_categories", {}).get(
        client.get("menu_category", ""), [],
    )
    return [{
        "name": DEFAULT_COUNTER_NAME,
        "categories": list(categories),
        "slot_counts": {
            slot: int(count) for slot, count in
            data.get("slot_count_overrides", {}).get(name, {}).items()
        },
        "theme_map": {
            day.lower(): theme for day, theme in
            data.get("theme_overrides", {}).get(name, {}).items()
        },
    }]


def _client_row(client, data):
    """Return the ``clients`` row for one entry of the JSON file."""
    counters = client.get("counters")
    if not counters:
        counters = _counters_from_legacy(client, data)
    return {
        "name": client["name"],
        "counters": counters,
        "city": client.get("city") or None,
        "serve_weekends": bool(client.get("serve_weekends", False)),
        "item_cooldown_days": int(client.get("item_cooldown_days", 20)),
        "source_pools": list(client.get("source_pools") or []),
    }


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase from clients.json")
    parser.add_argument(
        "--json",
        default=str(Path(__file__).parent.parent / "data" / "configs" / "clients.json"),
        help="Path to clients.json (default: data/configs/clients.json)",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY environment variables.")
        sys.exit(1)

    sb = create_client(url, key)

    with open(args.json) as f:
        data = json.load(f)

    # 1. Clients — counters, settings, and source pools all in one row.
    client_rows = [_client_row(c, data) for c in data["clients"]]
    empty = [r["name"] for r in client_rows if not r["counters"][0]["categories"]]
    if empty:
        print(
            "  WARNING: these clients have no categories and won't be "
            f"plannable until you fix them in the editor: {', '.join(empty)}"
        )
    sb.table("clients").upsert(client_rows).execute()
    print(f"  Upserted {len(client_rows)} clients")

    # 2. App settings. JSONB columns take real JSON, not a JSON string.
    settings = [
        {"key": "core_min_one_slots", "value": data.get("core_min_one_slots", [])},
        {"key": "constant_slots", "value": data.get("constant_slots", [])},
    ]
    sb.table("app_settings").upsert(settings).execute()
    print(f"  Upserted {len(settings)} app settings")

    print("\nDone! Supabase is now populated with your client configuration.")


if __name__ == "__main__":
    main()
