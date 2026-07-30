#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
SNAPSHOTS = ROOT / "data" / "snapshots"
CURRENT_SEASON = int(os.getenv("CURRENT_SEASON", "2026"))
PBP_SEASON = int(os.getenv("PBP_SEASON", "2025"))

URLS = {
    "pbp": f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{PBP_SEASON}.parquet",
    "rosters": f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{CURRENT_SEASON}.parquet",
    "players": "https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet",
}
SOURCE_CONFIG = ROOT / "config" / "data_sources.json"

TEAM_ALIASES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

COACH_URLS = {
    "head_coach": "https://en.wikipedia.org/wiki/List_of_current_National_Football_League_head_coaches",
    "offensive_coordinator": "https://en.wikipedia.org/wiki/List_of_current_NFL_offensive_coordinators",
    "defensive_coordinator": "https://en.wikipedia.org/wiki/List_of_current_NFL_defensive_coordinators",
}

OFFENSE_PREFIXES = {
    "passer", "receiver", "rusher", "lateral_receiver", "lateral_rusher",
    "fumbled_1", "fumbled_2",
}
DEFENSE_PREFIXES = {
    "interception", "tackle_with_assist_1", "tackle_with_assist_2",
    "solo_tackle_1", "solo_tackle_2", "assist_tackle_1", "assist_tackle_2",
    "forced_fumble_player_1", "forced_fumble_player_2", "half_sack_1",
    "half_sack_2", "sack_player",
}


def download(name: str, url: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / Path(url).name
    if path.exists() and path.stat().st_size:
        return path
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                handle.write(chunk)
    return path


def download_optional_sources() -> tuple[dict[str, Path], dict[str, dict]]:
    specs = json.loads(SOURCE_CONFIG.read_text())
    resolved: dict[str, Path] = {}
    status: dict[str, dict] = {}
    for name, spec in specs.items():
        season = spec.get("season") or PBP_SEASON
        errors = []
        for template in spec["candidates"]:
            url = template.format(season=season)
            try:
                resolved[name] = download(name, url)
                status[name] = {
                    "status": "ingested", "required": bool(spec["required"]),
                    "url": url, "grain": spec["grain"], "unlocks": spec["unlocks"],
                }
                break
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}")
        if name not in resolved:
            status[name] = {
                "status": "unavailable", "required": bool(spec["required"]),
                "grain": spec["grain"], "unlocks": spec["unlocks"], "attempts": errors,
            }
            if spec["required"]:
                raise RuntimeError(f"Required source {name} could not be downloaded")
    return resolved, status


def build_team_tendencies(pbp: pd.DataFrame) -> pd.DataFrame:
    plays = pbp.loc[pbp["posteam"].notna()].copy()
    plays["is_early_down"] = plays["down"].isin([1, 2])
    plays["is_late_down"] = plays["down"].isin([3, 4])
    plays["is_red_zone"] = pd.to_numeric(plays["yardline_100"], errors="coerce").le(20)
    plays["is_explosive"] = (
        (plays["pass"].fillna(0).eq(1) & plays["yards_gained"].fillna(0).ge(15))
        | (plays["rush"].fillna(0).eq(1) & plays["yards_gained"].fillna(0).ge(10))
    )
    rows = []
    situations = {
        "all": pd.Series(True, index=plays.index),
        "early_down": plays["is_early_down"],
        "late_down": plays["is_late_down"],
        "red_zone": plays["is_red_zone"],
    }
    for situation, mask in situations.items():
        for team, group in plays.loc[mask].groupby("posteam"):
            dropbacks = group["qb_dropback"].fillna(0)
            rushes = group["rush"].fillna(0)
            rows.append({
                "season": PBP_SEASON, "team": team, "situation": situation,
                "plays": len(group), "epa_per_play": group["epa"].mean(),
                "success_rate": group["success"].mean(),
                "pass_rate": dropbacks.sum() / max(1, dropbacks.sum() + rushes.sum()),
                "explosive_rate": group["is_explosive"].mean(),
            })
    return pd.DataFrame(rows)


def normalize_team(value: object) -> str | None:
    text = re.sub(r"\[\w+\]", "", str(value)).strip()
    return TEAM_ALIASES.get(text)


def find_tables(url: str) -> list[pd.DataFrame]:
    response = requests.get(
        url,
        headers={"User-Agent": "BrownsGamePlanData/1.0 (public analytics project)"},
        timeout=60,
    )
    response.raise_for_status()
    matches = []
    for table in pd.read_html(StringIO(response.text)):
        cols = [str(c).lower() for c in table.columns]
        if any("team" in c for c in cols) and any(
            token in " ".join(cols) for token in ("coach", "coordinator")
        ):
            matches.append(table)
    if not matches:
        raise RuntimeError(f"No coaching table found at {url}")
    return matches


def build_coaches() -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for role, url in COACH_URLS.items():
        pieces = []
        for table in find_tables(url):
            team_col = next(c for c in table.columns if "team" in str(c).lower())
            person_col = next(
                c for c in table.columns
                if ("coach" in str(c).lower() or "coordinator" in str(c).lower())
                and c != team_col
            )
            part = table[[team_col, person_col]].copy()
            part.columns = ["team_name", role]
            pieces.append(part)
        piece = pd.concat(pieces, ignore_index=True)
        piece["team"] = piece["team_name"].map(normalize_team)
        piece[role] = piece[role].astype(str).str.replace(r"\[\w+\]", "", regex=True).str.strip()
        piece = piece.dropna(subset=["team"]).drop_duplicates("team")[["team", role]]
        merged = piece if merged is None else merged.merge(piece, on="team", how="outer")
    assert merged is not None
    merged["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    merged["source_urls"] = " | ".join(COACH_URLS.values())
    return merged.sort_values("team")


def role_from_column(column: str) -> str:
    return re.sub(r"_player_id$", "", column)


def team_for_role(role: str, row: pd.Series) -> tuple[str | None, str, float]:
    if any(role.startswith(prefix) for prefix in OFFENSE_PREFIXES):
        return row.get("posteam"), "play_possession_team", 0.99
    if any(role.startswith(prefix) for prefix in DEFENSE_PREFIXES):
        return row.get("defteam"), "play_defense_team", 0.99
    if role.startswith(("returner", "punt_returner", "kickoff_returner")):
        return row.get("posteam"), "return_possession_team", 0.95
    if role.startswith("punter"):
        return row.get("posteam"), "punt_possession_team", 0.98
    if role.startswith("kicker"):
        if row.get("play_type") in {"extra_point", "field_goal"}:
            return row.get("posteam"), "scrimmage_kicking_team", 0.98
        return row.get("defteam"), "kickoff_kicking_team", 0.90
    return None, "unresolved_role", 0.0


def build_play_players(pbp: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    id_columns = [
        c for c in pbp.columns
        if c.endswith("_player_id") and c not in {"fantasy_player_id"}
    ]
    player_name_map = {}
    if "gsis_id" in players.columns and "display_name" in players.columns:
        player_name_map = players.set_index("gsis_id")["display_name"].dropna().to_dict()

    records: list[dict] = []
    base_cols = ["game_id", "play_id", "season", "week", "season_type",
                 "game_date", "posteam", "defteam", "play_type"]
    available_base = [c for c in base_cols if c in pbp.columns]
    for _, row in pbp[available_base + id_columns].iterrows():
        base = {c: row.get(c) for c in available_base}
        for col in id_columns:
            player_id = row.get(col)
            if pd.isna(player_id) or not str(player_id).strip():
                continue
            role = role_from_column(col)
            team, method, confidence = team_for_role(role, row)
            name_col = col.replace("_id", "_name")
            records.append({
                **base,
                "player_id": str(player_id),
                "player_name": (
                    row.get(name_col)
                    if name_col in pbp.columns and pd.notna(row.get(name_col))
                    else player_name_map.get(str(player_id))
                ),
                "role": role,
                "team": team,
                "assignment_method": method,
                "assignment_confidence": confidence,
                "source_column": col,
            })
    return pd.DataFrame.from_records(records).drop_duplicates(
        ["game_id", "play_id", "player_id", "role"]
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {name: download(name, url) for name, url in URLS.items()}
    pbp = pd.read_parquet(files["pbp"])
    rosters = pd.read_parquet(files["rosters"])
    players = pd.read_parquet(files["players"])
    extra_files, feed_status = download_optional_sources()

    pq.write_table(pa.Table.from_pandas(pbp, preserve_index=False), OUT / "plays_2025.parquet")
    pq.write_table(pa.Table.from_pandas(rosters, preserve_index=False), OUT / "rosters_current.parquet")
    play_players = build_play_players(pbp, players)
    pq.write_table(
        pa.Table.from_pandas(play_players, preserve_index=False),
        OUT / "play_players_2025.parquet",
    )
    coaches = build_coaches()
    coaches.to_csv(OUT / "coaches_current.csv", index=False)
    schemes = pd.read_csv(ROOT / "config" / "schemes_2026.csv")
    schemes.to_csv(OUT / "schemes_current.csv", index=False)
    tendencies = build_team_tendencies(pbp)
    tendencies.to_parquet(OUT / "team_tendencies_2025.parquet", index=False)
    extra_rows = {}
    for name, path in extra_files.items():
        frame = pd.read_parquet(path)
        frame.to_parquet(OUT / f"{name}.parquet", index=False)
        extra_rows[name] = len(frame)
    (OUT / "feed_status.json").write_text(json.dumps(feed_status, indent=2))

    outputs = sorted(OUT.glob("*"))
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "current_season": CURRENT_SEASON,
        "pbp_season": PBP_SEASON,
        "sources": URLS | COACH_URLS,
        "feed_status": feed_status,
        "rows": {
            "plays": len(pbp), "rosters": len(rosters),
            "play_players": len(play_players), "coaches": len(coaches),
            "schemes": len(schemes), "team_tendencies": len(tendencies),
            **extra_rows,
        },
        "outputs": {
            p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
            for p in outputs if p.is_file()
        },
    }
    (OUT / "build_manifest.json").write_text(json.dumps(manifest, indent=2))
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = SNAPSHOTS / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for artifact in OUT.iterdir():
        if artifact.is_file():
            (snapshot_dir / artifact.name).write_bytes(artifact.read_bytes())
    (SNAPSHOTS / "latest.json").write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "built_at": manifest["built_at"],
        "path": str(snapshot_dir.relative_to(ROOT)),
    }, indent=2))
    print(json.dumps(manifest["rows"], indent=2))


if __name__ == "__main__":
    main()
