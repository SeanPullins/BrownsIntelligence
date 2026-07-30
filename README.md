# Browns Intelligence

Public, evolving Browns opponent-scouting and game-plan project.

**Public dashboard:** https://seanpullins.github.io/BrownsIntelligence/

The site is deployed automatically through GitHub Actions after updates to `main`. GitHub Pages must be activated once at the account/repository level before GitHub can serve the public URL. Visitors do not need a ChatGPT or GitHub login.

## Current model checkpoint

- Seven seasons and 1,693 pregame examples
- Untouched 2025 test: 0.689 AUC and 0.222 Brier score
- Historical Browns-at-Jaguars baseline: 26.6%
- Final Week 1 forecast withheld until 2026 personnel, availability, usage and scheme readiness gates pass

## Data framework

The reproducible pipeline ingests public nflverse play-by-play, rosters, schedules, participation, snap counts, FTN charting, injuries, and weekly summaries as available. Every evolving input carries source, retrieval time, effective date, season/week, snapshot and confidence metadata.

> Independent analysis. Not affiliated with the Cleveland Browns or the NFL.
