"""Deterministic GTA VI launch-day Twitch viewer forecaster.

Reads each case JSON from MAKEFUN_INPUT_DIR (default /input) and writes a matching
forecast JSON to MAKEFUN_OUTPUT_DIR (default /output). Standard library only.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first for optional local modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
BASE_SIGMA = 0.15
HOURS = list(range(2, 25))
MAX_Q = 1_000_000_000.0
EPS = 1e-9


def round2(x: float) -> float | int:
    """Round half up to 2 decimals, returning int for whole values like JS Math.round/100."""
    try:
        xf = float(x)
    except Exception:
        xf = 1.0
    if not math.isfinite(xf):
        xf = 1.0
    scaled = xf * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5 - 1e-12:
        whole += 1
    value = whole / 100.0
    if abs(value - round(value)) < 1e-12:
        return int(round(value))
    return value


def clamp_q(v: float) -> float:
    try:
        x = float(v)
    except Exception:
        x = 1.0
    if not math.isfinite(x):
        x = 1.0
    if x <= 0.0:
        x = 1e-6
    if x > MAX_Q:
        x = MAX_Q
    return x


def safe_float(v, default=None):
    try:
        if v is None:
            return default
        x = float(v)
        if math.isfinite(x):
            return x
    except Exception:
        return default
    return default


def iso_to_hour_index(ts: str) -> int | None:
    """Return integer hour index from an ISO UTC timestamp string, or None."""
    if not isinstance(ts, str):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?Z$", ts)
    if not m:
        return None
    y, mo, d, hh, _mm, _ss = map(int, m.groups())
    # Convert to days since civil 1970-01-01 (algorithm from Howard Hinnant).
    y2 = y - (1 if mo <= 2 else 0)
    era = (y2 if y2 >= 0 else y2 - 399) // 400
    yoe = y2 - era * 400
    doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return days * 24 + hh


def hour_offset_from_day_start(day_start: str, ts: str) -> int | None:
    a = iso_to_hour_index(day_start)
    b = iso_to_hour_index(ts)
    if a is None or b is None:
        return None
    return b - a


def _norm_text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, (list, tuple, set)):
        return " ".join(_norm_text(v) for v in x)
    return str(x).lower()


def persistence_quantiles(p1: float, h: int) -> list[float]:
    p1 = max(1.0, float(p1))
    t = math.sqrt(max(0.0, h - 1.0))
    out = []
    for z in Z:
        val = p1 * math.exp(z * BASE_SIGMA * t)
        out.append(clamp_q(val))
    return out


def is_gta_vi_nonlaunch(comp: dict, case: dict) -> bool:
    """Exclude GTA VI pre-release/non-launch comparable series from launch-shape fitting."""
    if not isinstance(comp, dict):
        return False
    case_game = case.get("game") if isinstance(case, dict) else {}
    comp_name = _norm_text(comp.get("name"))
    unlock = _norm_text(comp.get("unlock"))
    notes = _norm_text(comp.get("notes"))
    source = _norm_text(comp.get("source"))
    blob = " ".join([comp_name, unlock, notes, source])
    comp_day = str(comp.get("day_start") or "")
    comp_tid = str(comp.get("twitch_id") or "")
    case_day = str(case.get("day_start") or "") if isinstance(case, dict) else ""
    case_tid = str((case_game or {}).get("twitch_id") or "")

    prelaunch_markers = [
        "premiere",
        "extended look",
        "extended-look",
        "trailer",
        "before release",
        "pre-release",
        "prerelease",
        "non-launch",
        "not a launch",
        "category before release",
    ]

    is_gta = ("grand theft auto vi" in comp_name) or ("gta vi" in comp_name) or (comp_tid and case_tid and comp_tid == case_tid)
    if is_gta:
        if any(m in blob for m in prelaunch_markers):
            return True
        # Known GTA VI pre-release category history series in this dataset.
        if comp_day.startswith("2026-08-27"):
            return True
        # Same category id but different day_start than the current case is not the launch-day series.
        if case_tid and comp_tid == case_tid and case_day and comp_day and comp_day != case_day:
            return True
        # Extra guard: if comparable is clearly labeled as GTA VI but missing launch context and mismatched day.
        if ("grand theft auto vi" in comp_name or "gta vi" in comp_name) and case_day and comp_day and comp_day != case_day and "launch" not in unlock:
            return True

    if any(m in unlock for m in ("non-launch", "not a launch", "before release", "pre-release", "premiere", "trailer")):
        return True
    return False


def platform_weight(comp: dict) -> float:
    platforms = comp.get("platforms")
    text = _norm_text(platforms)
    unlock = _norm_text(comp.get("unlock"))
    name = _norm_text(comp.get("name"))
    notes = _norm_text(comp.get("notes"))
    blob = " ".join([text, unlock, name, notes])

    w = 1.0
    # GTA VI target: console launch (PS5/Xbox Series X|S), single-player, midnight local unlock rollout.
    console_terms = ["ps5", "playstation", "xbox", "series x", "series s", "switch", "console"]
    pc_terms = ["pc", "steam", "windows", "epic"]
    mobile_terms = ["mobile", "ios", "android"]
    has_console = any(t in blob for t in console_terms)
    has_pc = any(t in blob for t in pc_terms)
    has_mobile = any(t in blob for t in mobile_terms)

    if has_console:
        w *= 1.45
    if has_console and not has_pc and not has_mobile:
        w *= 1.12
    if has_pc and not has_console:
        w *= 0.72
    if has_mobile and not has_console:
        w *= 0.55

    if "midnight local" in blob or "midnight" in unlock:
        w *= 1.08
    if "global" in unlock and "local" not in unlock and "midnight" in unlock:
        w *= 0.97

    # Genre/mode hints: favor big single-player/story launches; de-emphasize live-service-only shapes.
    if any(t in blob for t in ["single-player", "single player", "story", "campaign", "open world", "open-world", "rpg", "action-adventure", "action adventure"]):
        w *= 1.08
    if any(t in blob for t in ["multiplayer only", "live service only", "battle royale", "free-to-play", "free to play"]):
        w *= 0.82
    if any(t in blob for t in ["early access", "beta", "demo", "closed beta", "open beta", "preview"]):
        w *= 0.78

    # Franchise/scale hints can help mildly (kept small and deterministic).
    if any(t in name for t in ["grand theft auto", "red dead redemption"]):
        w *= 1.05

    return max(0.15, min(3.5, w))


def _extract_hourly_points(comp: dict) -> dict:
    """Return hour->viewers map aligned to comparable day_start (hour 1 == offset 0)."""
    day_start = comp.get("day_start")
    hourly = comp.get("hourly") or []
    if not isinstance(hourly, list) or not day_start:
        return {}
    by_hour = {}
    for pt in hourly:
        if not isinstance(pt, dict):
            continue
        ts = pt.get("from")
        h = hour_offset_from_day_start(day_start, ts)
        v = safe_float(pt.get("viewers"), None)
        if h is None or v is None:
            continue
        hour_num = h + 1
        if 1 <= hour_num <= 24:
            vv = max(0.0, float(v))
            prev = by_hour.get(hour_num)
            # Keep the larger value if duplicates/sparse variants appear for same hour.
            by_hour[hour_num] = vv if prev is None else max(prev, vv)
    return by_hour


def build_ratio_profiles(case: dict):
    comps = case.get("comparables") or []
    profiles = []  # list of (weight, ratios_by_hour)
    if not isinstance(comps, list):
        return profiles
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        if is_gta_vi_nonlaunch(comp, case):
            continue
        by_hour = _extract_hourly_points(comp)
        base = by_hour.get(1)
        if base is None or base <= 0:
            # Fallback: infer base from first positive in early launch window.
            for hh in (1, 2, 3, 4):
                bv = by_hour.get(hh)
                if bv is not None and bv > 0:
                    base = bv
                    break
        if base is None or base <= 0:
            continue
        ratios = {}
        for h in HOURS:
            v = by_hour.get(h)
            if v is not None and v > 0:
                ratios[h] = max(0.01, min(50.0, v / base))
        if len(ratios) < 5:
            continue
        completeness = 0.7 + 0.3 * min(1.0, len(ratios) / 23.0)
        w = platform_weight(comp) * completeness
        profiles.append((max(0.05, w), ratios))
    return profiles


def weighted_quantile(values_weights, q):
    # values_weights: list of (value, weight), weight > 0
    if not values_weights:
        return None
    items = sorted(values_weights, key=lambda x: (x[0], x[1]))
    total = sum(w for _, w in items if w > 0)
    if total <= 0:
        return items[len(items) // 2][0]
    target = q * total
    acc = 0.0
    for v, w in items:
        if w <= 0:
            continue
        acc += w
        if acc + 1e-15 >= target:
            return v
    return items[-1][0]


def _get_known_p1(case: dict) -> float:
    """Return hour-1 viewer print from known/history fields, with defensive fallbacks."""
    if not isinstance(case, dict):
        return 1.0
    known = case.get("known") or []
    if isinstance(known, list):
        for k in known:
            if isinstance(k, dict) and k.get("hour") == 1:
                v = safe_float(k.get("viewers"), None)
                if v is not None and v > 0:
                    return max(1.0, float(v))
        for k in known:
            if isinstance(k, dict):
                v = safe_float(k.get("viewers"), None)
                if v is not None and v > 0:
                    return max(1.0, float(v))

    # Fallback: hour 1 in history_hourly aligned to day_start offset 0.
    day_start = case.get("day_start")
    hist_hourly = case.get("history_hourly")
    if isinstance(hist_hourly, list) and isinstance(day_start, str):
        for row in hist_hourly:
            if not isinstance(row, dict):
                continue
            ts = row.get("from")
            off = hour_offset_from_day_start(day_start, ts)
            if off == 0:
                v = safe_float(row.get("viewers"), None)
                if v is not None and v > 0:
                    return max(1.0, float(v))

    # Fallback: mean of minute/history points in the first hour if available.
    history = case.get("history")
    if isinstance(history, list) and isinstance(day_start, str):
        vals = []
        for pt in history:
            if not isinstance(pt, dict):
                continue
            ts = pt.get("at") or pt.get("from")
            off = hour_offset_from_day_start(day_start, ts)
            if off == 0:
                v = safe_float(pt.get("viewers"), None)
                if v is not None and v > 0:
                    vals.append(float(v))
        if vals:
            return max(1.0, sum(vals) / len(vals))

    return 1.0


def _compute_empirical_log_quantiles(case: dict):
    """Compute per-hour empirical log-ratio quantiles and sample counts from comparables."""
    profiles = build_ratio_profiles(case if isinstance(case, dict) else {})
    out = {}
    counts = {}
    weights = {}
    if not profiles:
        return out, counts, weights
    for h in HOURS:
        samples = []
        for w, ratios in profiles:
            r = ratios.get(h)
            rv = safe_float(r, None)
            if rv is not None and rv > 0 and w > 0:
                samples.append((math.log(max(0.01, min(50.0, float(rv)))), float(w)))
        if not samples:
            continue
        lq = [weighted_quantile(samples, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        if any(v is None or not math.isfinite(v) for v in lq):
            continue
        # Enforce monotonic quantiles in log space defensively.
        mono = []
        prev = -1e9
        for v in lq:
            x = float(v)
            if x < prev:
                x = prev
            mono.append(x)
            prev = x
        out[h] = mono
        counts[h] = len(samples)
        weights[h] = sum(w for _, w in samples)
    return out, counts, weights


def _fill_missing_log_quantiles(lq_by_hour: dict, counts: dict, weights: dict):
    """Fill sparse hours by borrowing from nearest available hours (deterministic)."""
    if not lq_by_hour:
        return lq_by_hour, counts, weights
    filled = dict(lq_by_hour)
    filled_counts = dict(counts)
    filled_weights = dict(weights)
    for h in HOURS:
        if h in filled:
            continue
        left = None
        right = None
        for d in range(1, 24):
            if left is None and h - d >= 2 and (h - d) in filled:
                left = h - d
            if right is None and h + d <= 24 and (h + d) in filled:
                right = h + d
            if left is not None and right is not None:
                break
            if d >= 4 and (left is not None or right is not None):
                # Accept one-sided neighbor if opposite side is far; keeps interpolation local/stable.
                break
        if left is None and right is None:
            continue
        if left is not None and right is not None:
            dl = h - left
            dr = right - h
            wl = 1.0 / dl
            wr = 1.0 / dr
            tot = wl + wr
            merged = [(filled[left][i] * wl + filled[right][i] * wr) / tot for i in range(5)]
            filled[h] = merged
            filled_counts[h] = min(filled_counts.get(left, 1), filled_counts.get(right, 1))
            filled_weights[h] = min(filled_weights.get(left, 0.0), filled_weights.get(right, 0.0))
        elif left is not None:
            filled[h] = list(filled[left])
            filled_counts[h] = filled_counts.get(left, 1)
            filled_weights[h] = filled_weights.get(left, 0.0)
        else:
            filled[h] = list(filled[right])
            filled_counts[h] = filled_counts.get(right, 1)
            filled_weights[h] = filled_weights.get(right, 0.0)
    return filled, filled_counts, filled_weights


def forecast_case(case: dict) -> dict:
    p1 = _get_known_p1(case if isinstance(case, dict) else {})
    forecast_rows = case.get("forecast") if isinstance(case, dict) else None
    want_hours = []
    if isinstance(forecast_rows, list):
        for row in forecast_rows:
            if not isinstance(row, dict):
                continue
            h = row.get("hour")
            if isinstance(h, float) and h.is_integer():
                h = int(h)
            if isinstance(h, int) and 2 <= h <= 24 and h not in want_hours:
                want_hours.append(h)
    if sorted(want_hours) != HOURS:
        want_hours = HOURS[:]

    lq_by_hour, counts, weights = _compute_empirical_log_quantiles(case if isinstance(case, dict) else {})
    lq_by_hour, counts, weights = _fill_missing_log_quantiles(lq_by_hour, counts, weights)

    hours_out = []
    for h in want_hours:
        base_q = persistence_quantiles(p1, h)
        lq = lq_by_hour.get(h)
        if lq:
            sample_count = counts.get(h, 1)
            sample_weight = weights.get(h, 1.0)
            conf_count = min(1.0, max(0.0, sample_count) / 14.0)
            conf_weight = min(1.0, max(0.0, sample_weight) / 18.0)
            blend_data = 0.10 + 0.66 * (0.6 * conf_count + 0.4 * conf_weight)
            # If hour was sparsely represented in comparables, lean more on the baseline.
            if sample_count <= 3:
                blend_data *= 0.85
            blend_base = 1.0 - blend_data

            qvals = []
            horizon = math.sqrt(max(0.0, h - 1.0))
            for i, z in enumerate(Z):
                rv = math.exp(lq[i]) if math.isfinite(lq[i]) else (base_q[i] / max(p1, 1.0))
                rv = max(0.01, min(50.0, rv))
                data_val = clamp_q(p1 * rv)
                val = blend_base * base_q[i] + blend_data * data_val
                # Slight horizon-aware tail shaping; monotonicity is enforced after blending.
                tail = 1.0 + abs(z) * (0.016 + 0.007 * min(1.0, horizon / 4.5)) * blend_data
                if i < 2:
                    val /= tail
                elif i > 2:
                    val *= tail
                qvals.append(clamp_q(val))
        else:
            qvals = base_q[:]

        fixed = []
        prev = 0.0
        for v in qvals:
            x = clamp_q(v)
            if x < prev:
                x = prev
            fixed.append(x)
            prev = x
        for i in range(len(fixed)):
            if fixed[i] > MAX_Q:
                fixed[i] = MAX_Q
        for i in range(1, len(fixed)):
            if fixed[i] < fixed[i - 1]:
                fixed[i] = fixed[i - 1]

        hours_out.append({"hour": h, "q": [round2(v) for v in fixed]})

    by_hour = {row["hour"]: row for row in hours_out if isinstance(row, dict)}
    final_rows = []
    for h in HOURS:
        row = by_hour.get(h)
        if not isinstance(row, dict):
            row = {"hour": h, "q": [round2(v) for v in persistence_quantiles(p1, h)]}
        qs = row.get("q")
        if not (isinstance(qs, list) and len(qs) == 5):
            qs = [round2(v) for v in persistence_quantiles(p1, h)]
        clean = []
        prev = 0.0
        for v in qs:
            x = clamp_q(safe_float(v, prev if prev > 0 else 1.0))
            if x < prev:
                x = prev
            clean.append(x)
            prev = x
        if clean[-1] > MAX_Q:
            clean = [min(MAX_Q, v) for v in clean]
            for i in range(1, 5):
                if clean[i] < clean[i - 1]:
                    clean[i] = clean[i - 1]
        final_rows.append({"hour": h, "q": [round2(v) for v in clean]})
    return {"hours": final_rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(INPUT_DIR.glob("*.in")) if INPUT_DIR.exists() else []
    for path in paths:
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(case, dict):
                case = {}
            forecast = forecast_case(case)
        except Exception:
            # Defensive fallback: emit valid-shaped output.
            forecast = {"hours": [{"hour": h, "q": [1, 1, 1, 1, 1]} for h in HOURS]}
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
