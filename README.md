# GTA VI Launch-Day Twitch Viewer Forecaster

[![Competition](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Qentak/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Qentak/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Deterministic, standard-library-only Python 3.13 forecaster for the Make.fun bounty **Forecast GTA VI's launch-day Twitch viewers hour by hour** (`gta6-twitch-ccu-forecast-01`).

## What it does

- Reads every `*.in` JSON case file from `MAKEFUN_INPUT_DIR` (default `/input`), in filename order.
- Writes a matching `*.out` JSON forecast file to `MAKEFUN_OUTPUT_DIR` (default `/output`).
- Produces exactly 23 forecast rows for hours `2` through `24`, each with five finite, positive, non-decreasing quantiles (`q05, q25, q50, q75, q95`) at or below `1,000,000,000`.
- Anchors forecasts to hour 1's known viewer print and blends a persistence baseline with comparable launch-day hourly ratio profiles.
- Aligns comparable hourly series to each comparable's `day_start` (UTC) so hour 1 corresponds to offset 0 before computing hour-by-hour ratios.
- Excludes GTA VI non-launch/pre-release historical comparable series using identity, `twitch_id`, `day_start`, and unlock/metadata markers.
- Applies platform-aware weighting to emphasize console, single-player, midnight-local launches and de-emphasize mismatched launch types.
- Uses weighted empirical ratio quantiles in log space with confidence-based blending for robust, deterministic forecasts.
- Fills sparse comparable-hour coverage by borrowing from nearby hours and falls back to a widening persistence baseline when data is thin or malformed.
- Handles malformed or sparse inputs defensively and runs without network access or third-party packages.

## Run locally

```bash
mkdir -p out
MAKEFUN_INPUT_DIR=.local-context/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

This reads the local practice/example input cases and writes corresponding `.out` forecast files to `out/`.

To run in the grader-style layout, place case files in `/input` and run:

```bash
python3 /bot/main.py
```

(`python3 main.py` from the repository root also works when `MAKEFUN_INPUT_DIR`/`MAKEFUN_OUTPUT_DIR` are set appropriately.)
