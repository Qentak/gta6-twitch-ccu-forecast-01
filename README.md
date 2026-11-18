# GTA6 Twitch CCU Forecast (Make.fun)

Deterministic, stdlib-only Python 3 forecaster that produces hour-2..24 Twitch CCU quantile estimates from launch-hour context and comparable release curves. It reads contest JSON inputs, aligns comparable hourly points to each release window in UTC, builds weighted log-ratio distributions, then outputs non-decreasing `p5/p25/p50/p75/p95` quantiles per hour.

[![GTA6 Twitch CCU Forecast](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Qentak/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Qentak/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

## Run (Python)

```bash
export MAKEFUN_INPUT_DIR=/input
export MAKEFUN_OUTPUT_DIR=/output
python3 main.py
```

- Input: `*.in` JSON files in `MAKEFUN_INPUT_DIR` (default `/input`)
- Output: corresponding `*.out` JSON in `MAKEFUN_OUTPUT_DIR` (default `/output`) with `{"hours":[{"hour":2..24,"q":[p5,p25,p50,p75,p95]},...]}` (integers, non-decreasing, clamped to `[1, 1000000000]`)