# Browns Intelligence — Game Plan Data Foundation

Reproducible data pipeline for the Browns opponent/game-plan model.

Live product: https://browns-game-plan.seanpullins.chatgpt.site

This repository is the evolving, reproducible data foundation. Generated NFL
datasets are rebuilt by GitHub Actions and stored as workflow artifacts rather
than committed to Git.

It builds:

- current NFL season rosters from nflverse
- current head coaches, offensive coordinators, and defensive coordinators
- a dated, editable 32-team scheme classification
- every 2025 nflverse play
- a normalized play-to-player bridge that assigns each referenced player to the
  correct team for that play wherever the play context supports it
- weekly rosters and schedules
- snap counts, participation, FTN charting, injuries, and weekly player/team
  summaries whenever the public season asset is available
- explainable all-down, early-down, late-down, and red-zone team tendencies

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_data.py
python scripts/validate_data.py
```

Generated data is written to `data/processed/` and is intentionally ignored by
Git. GitHub Actions rebuilds it as a downloadable workflow artifact.

## Outputs

| File | Grain |
|---|---|
| `rosters_current.parquet` | one player/team roster record |
| `coaches_current.csv` | one team with HC/OC/DC |
| `schemes_current.csv` | one team with offense/defense scheme labels |
| `plays_2025.parquet` | one nflverse play |
| `play_players_2025.parquet` | one player-role assignment per play |
| `weekly_rosters.parquet` | one player/team/week |
| `schedules.parquet` | one NFL game |
| `team_tendencies_2025.parquet` | one team/situation feature row |
| `snap_counts.parquet` | one player/game, when available |
| `participation.parquet` | one play participation record, when available |
| `ftn_charting.parquet` | one charted play, when available |
| `injuries.parquet` | one player/week report, when available |
| `feed_status.json` | source, grain, availability, and unlocked features |
| `build_manifest.json` | source URLs, timestamps, row counts, hashes |
| `validation_report.json` | coverage and integrity checks |

## Important definitions

“Current” means the configured `CURRENT_SEASON` (2026 by default), not the
player’s 2025 team. Scheme labels are scouting classifications, not official NFL
fields. They are stored separately with confidence, source notes, and an
`as_of_date`.

The raw 2025 play table already contains role-specific GSIS player IDs. The
bridge table converts those wide fields (`passer_player_id`,
`receiver_player_id`, `tackle_with_assist_1_player_id`, etc.) into rows and
assigns a play-time team from possession/defense/special-teams context. It never
silently substitutes a current roster team for a historical play team.

Optional feeds are deliberately non-fatal. nflverse asset names and season
coverage can vary; every attempted source is recorded as `ingested` or
`unavailable` in `feed_status.json`. Required feeds fail the build.

## Data sources and license

- nflverse automated data releases: CC BY 4.0
- nflverse player registry for cross-source player identifiers
- public current-coach lists, captured with source URL and retrieval date

Review downstream distribution requirements and retain nflverse attribution.
# Preseason ingestion framework

The pipeline is designed to evolve safely through Week 1. It rebuilds daily,
keeps immutable timestamped snapshots, validates team/player joins, and produces
`preseason_readiness.json` so missing data lowers confidence instead of being
silently treated as current.

The collection plan has four phases:

1. Training camp — transactions, rosters, coaches, depth charts and injuries.
2. Preseason games — snaps, participation, formations, personnel and battles.
3. Roster cutdown — 53-man roster, waivers, practice squad and specialists.
4. Week 1 lock — practice reports, starters, weather and inactive risk.

Every future adapter should preserve `source`, `retrieved_at`, `effective_at`,
`season`, `week`, `team`, `snapshot_id`, and `confidence` where applicable.
