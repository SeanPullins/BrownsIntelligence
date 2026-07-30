#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
NFL_TEAMS = 32


def main() -> None:
    pbp = pd.read_parquet(OUT / "plays_2025.parquet")
    rosters = pd.read_parquet(OUT / "rosters_current.parquet")
    bridge = pd.read_parquet(OUT / "play_players_2025.parquet")
    coaches = pd.read_csv(OUT / "coaches_current.csv")
    schemes = pd.read_csv(OUT / "schemes_current.csv")
    tendencies = pd.read_parquet(OUT / "team_tendencies_2025.parquet")
    feed_status = json.loads((OUT / "feed_status.json").read_text())

    play_keys = pbp[["game_id", "play_id"]].drop_duplicates()
    orphaned = bridge.merge(play_keys, on=["game_id", "play_id"], how="left", indicator=True)
    report = {
        "checks": {
            "plays_unique": not pbp.duplicated(["game_id", "play_id"]).any(),
            "no_orphan_player_assignments": bool((orphaned["_merge"] == "both").all()),
            "coach_team_count_32": int(coaches["team"].nunique()) == NFL_TEAMS,
            "scheme_team_count_32": int(schemes["team"].nunique()) == NFL_TEAMS,
            "roster_team_count_32": int(rosters["team"].nunique()) == NFL_TEAMS,
            "tendencies_team_count_32": int(tendencies["team"].nunique()) == NFL_TEAMS,
        },
        "coverage": {
            "plays": len(pbp),
            "games": int(pbp["game_id"].nunique()),
            "player_role_rows": len(bridge),
            "unique_players_in_plays": int(bridge["player_id"].nunique()),
            "team_assignment_rate": float(bridge["team"].notna().mean()),
            "player_name_rate": float(bridge["player_name"].notna().mean()),
            "unresolved_role_rows": int(bridge["team"].isna().sum()),
            "ingested_extra_feeds": sum(v["status"] == "ingested" for v in feed_status.values()),
            "unavailable_optional_feeds": [
                k for k, v in feed_status.items()
                if v["status"] != "ingested" and not v["required"]
            ],
        },
    }
    report["passed"] = all(report["checks"].values())
    (OUT / "validation_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
