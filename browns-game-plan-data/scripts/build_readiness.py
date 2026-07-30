#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
PLAN = json.loads((ROOT / "config" / "preseason_collection_plan.json").read_text())


def main() -> None:
    status_path = OUT / "feed_status.json"
    statuses = json.loads(status_path.read_text()) if status_path.exists() else {}
    aliases = {
        "current_rosters": "rosters",
        "weekly_rosters": "weekly_rosters",
        "snap_counts": "snap_counts",
        "participation": "participation",
        "ftn_charting": "ftn_charting",
        "injuries": "injuries",
        "schedules": "schedules",
    }
    manual = {
        "transactions", "coaches", "depth_charts", "scheme_registry",
        "manual_film_observations", "practice_reports", "venue_weather",
    }
    gates = {}
    for gate, requirements in PLAN["readiness_gates"].items():
        items = []
        for name in requirements:
            feed = aliases.get(name, name)
            if name in manual:
                state = "review_required"
            elif feed == "rosters":
                state = "ingested"
            else:
                state = statuses.get(feed, {}).get("status", "not_configured")
            items.append({"input": name, "status": state})
        ready = sum(item["status"] == "ingested" for item in items)
        gates[gate] = {
            "score": round(100 * ready / len(items)),
            "ready_inputs": ready,
            "total_inputs": len(items),
            "inputs": items,
        }

    now = datetime.now(timezone.utc)
    phase = next(
        (p for p in PLAN["phases"] if now.date().isoformat() <= p["through"]),
        {"id": "regular_season", "label": "Regular season", "cadence": "weekly", "focus": []},
    )
    report = {
        "generated_at": now.isoformat(),
        "season_start": PLAN["season_start"],
        "current_phase": phase,
        "gates": gates,
        "overall_score": round(sum(g["score"] for g in gates.values()) / len(gates)),
        "publish_forecast": all(gates[g]["score"] >= 50 for g in ("identity", "usage", "availability")),
        "rule": "Missing, stale, or review-required inputs reduce readiness; they are never silently assumed current."
    }
    (OUT / "preseason_readiness.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
