#!/usr/bin/env python3
"""
Original compact forecasting script (Python 3 stdlib only).

Contract:
- Find *.in in MAKEFUN_INPUT_DIR (default /input)
- Read each as JSON
- Write corresponding <basename>.out into MAKEFUN_OUTPUT_DIR (default /output)
- Output JSON: {"hours": [ { "hour": 2..24, "q": [p5,p25,p50,p75,p95] }, ... ]}

Revised behavior (per instructions):
- Comparable hourly series may begin up to 14 days before release: parse comparable.day_start
  and each hourly.from as UTC datetimes. Retain only points at or after day_start and before
  day_start + 24h. Map elapsed hours to release hours 1..24 (hour 1 = first in-window point
  aligned to start boundary by elapsed floor hours from day_start: elapsed = (t - day_start).
  hours = floor(elapsed.total_seconds()/3600)+1, keep 1..24). Skip comparables without valid
  launch hour 1 (no in-window point mapping to hour 1).
- Exclude GTA VI non-launch historical series by checking comparable name and unlock (not date/from).
- Favor comparable console launches by platforms/unlock strings; downweight early-access or global
  PC-only launches.
- Non-positive known counts and error fallback must produce valid strictly positive quantiles (>=1, <=1e9).
- Protect exponentiation against overflow. Pure stdlib, no network.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from glob import glob
from typing import Any, Dict, List, Optional, Tuple


def parse_utc_dt(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    st = s.strip()
    if not st:
        return None
    # Try common ISO-8601 UTC forms
    try:
        # Python 3.11+ supports 'Z' via fromisoformat in some cases? Be safe.
        if st.endswith("Z"):
            st2 = st[:-1] + "+00:00"
        else:
            st2 = st
        dt = datetime.fromisoformat(st2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass
    # Fallback: try without microseconds variations
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            dt = datetime.strptime(st, fmt)
            dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            continue
    return None


def is_gta_vi_nonlaunch_historical(comp: Dict[str, Any]) -> bool:
    """Exclude GTA VI non-launch historical series by checking comparable name and unlock."""
    # Check name
    name = comp.get("name")
    if isinstance(name, str):
        nl = name.lower()
        if "gta vi" in nl or "gta 6" in nl or "grand theft auto vi" in nl:
            # If marked historical/non-launch in name/unlock, exclude
            if "histor" in nl or "non-launch" in nl or "nonlaunch" in nl:
                return True
            # Also exclude if name clearly says historical
    # Check unlock
    unlock = comp.get("unlock")
    if isinstance(unlock, str):
        ul = unlock.lower()
        if "gta vi" in ul or "gta 6" in ul or "grand theft auto vi" in ul:
            if "histor" in ul or "non-launch" in ul or "nonlaunch" in ul:
                return True
    # Check other common fields
    for key in ("title", "game", "category"):
        v = comp.get(key)
        if isinstance(v, str):
            vl = v.lower()
            if ("gta vi" in vl or "gta 6" in vl) and ("histor" in vl or "non-launch" in vl or "nonlaunch" in vl):
                return True
    return False


def parse_viewers(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if v < 0:
            return None
        return float(v)
    try:
        fv = float(str(v).replace(",", "").strip())
        if fv < 0 or math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    except Exception:
        return None


def compute_comp_weight(comp: Dict[str, Any]) -> float:
    """Favor console launches by platforms/unlock; downweight early-access or global PC-only."""
    w = 1.0
    text_parts: List[str] = []
    for key in ("platforms", "platform", "unlock", "release_type", "notes"):
        v = comp.get(key)
        if isinstance(v, str):
            text_parts.append(v.lower())
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    text_parts.append(it.lower())
    blob = " ".join(text_parts)

    # Favor console launches
    console_markers = ["ps5", "playstation", "xbox", "series x", "series s", "switch", "console"]
    if any(m in blob for m in console_markers):
        w += 1.5
    # Downweight early access
    if "early access" in blob or "early-access" in blob:
        w -= 0.8
    # Downweight global PC-only launches
    if ("pc" in blob or "steam" in blob or "windows" in blob) and not any(m in blob for m in console_markers):
        # pc-only/global pc-only
        if "global" in blob or "pc-only" in blob or "pc only" in blob or "only pc" in blob:
            w -= 0.7
        else:
            # still slight downweight if clearly pc focused and no console
            w -= 0.3

    if w < 0.2:
        w = 0.2
    if w > 3.0:
        w = 3.0
    return w


def build_hour1_and_ratios(comp: Dict[str, Any]) -> Optional[Dict[int, float]]:
    """
    Parse day_start and hourly.from (UTC). Keep points in [day_start, day_start+24h).
    Map to hour = floor((t-day_start).total_seconds()/3600)+1, clamp to 1..24.
    Return dict hour->viewers for hours that have values, but only if hour 1 exists.
    """
    ds = parse_utc_dt(comp.get("day_start"))
    if ds is None:
        return None
    hourly = comp.get("hourly")
    if not isinstance(hourly, list):
        return None
    end = ds + timedelta(hours=24)
    hour_map: Dict[int, float] = {}
    for pt in hourly:
        if not isinstance(pt, dict):
            continue
        t = parse_utc_dt(pt.get("from"))
        if t is None:
            continue
        if t < ds or t >= end:
            continue
        dt_sec = (t - ds).total_seconds()
        if dt_sec < 0:
            continue
        hnum = int(math.floor(dt_sec / 3600.0)) + 1
        if hnum < 1 or hnum > 24:
            continue
        v = parse_viewers(pt.get("viewers"))
        if v is None or v <= 0:
            continue
        # keep first seen or latest? use first
        if hnum not in hour_map:
            hour_map[hnum] = v
    if 1 not in hour_map:
        return None
    return hour_map


def build_log_ratio_samples(comparables: List[Dict[str, Any]]) -> Dict[int, List[Tuple[float, float]]]:
    samples: Dict[int, List[Tuple[float, float]]] = {h: [] for h in range(2, 25)}
    for comp in comparables:
        if not isinstance(comp, dict):
            continue
        if is_gta_vi_nonlaunch_historical(comp):
            continue
        hmap = build_hour1_and_ratios(comp)
        if hmap is None:
            continue
        v1 = hmap.get(1)
        if v1 is None or v1 <= 0:
            continue
        w = compute_comp_weight(comp)
        for hnum in range(2, 25):
            vh = hmap.get(hnum)
            if vh is None or vh <= 0:
                continue
            ratio = vh / v1
            if ratio <= 0:
                continue
            lr = math.log(ratio)
            if math.isnan(lr) or math.isinf(lr):
                continue
            samples[hnum].append((lr, w))
    return samples


def weighted_quantiles(values_weights: List[Tuple[float, float]], qs: List[float]) -> List[float]:
    if not values_weights:
        return [float("nan")] * len(qs)
    expanded: List[float] = []
    for val, w in values_weights:
        wi = int(round(w)) if isinstance(w, (int, float)) else 1
        if wi < 1:
            wi = 1
        if wi > 50:
            wi = 50
        for _ in range(wi):
            expanded.append(val)
    if not expanded:
        return [float("nan")] * len(qs)
    expanded.sort()
    n = len(expanded)
    out: List[float] = []
    for q in qs:
        if n <= 1:
            out.append(expanded[0])
            continue
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            out.append(expanded[lo])
        else:
            frac = pos - lo
            val = expanded[lo] * (1.0 - frac) + expanded[hi] * frac
            out.append(val)
    return out


def clamp_and_round_q(qvals: List[float], base_v1: float) -> List[int]:
    # Convert log-ratios to counts with overflow protection
    ratios: List[Optional[float]] = []
    for lv in qvals:
        if lv != lv or math.isinf(lv):
            ratios.append(None)
            continue
        # protect exp overflow: ln(max_ratio) ~ ln(1e9 / base_v1) but base_v1 can be small; cap lv
        if lv > 50.0:  # exp(50) is large but we clamp after
            lv = 50.0
        if lv < -80.0:
            lv = -80.0
        try:
            r = math.exp(lv)
        except OverflowError:
            r = float("inf")
        ratios.append(r)
    counts: List[Optional[int]] = []
    for r in ratios:
        if r is None:
            counts.append(None)
        else:
            if math.isinf(r):
                c = float(1000000000.0)
            else:
                c = r * base_v1
            if c < 0:
                c = 0.0
            if c > 1000000000.0:
                c = 1000000000.0
            counts.append(int(round(c)))
    # fill None
    for i in range(len(counts)):
        if counts[i] is None:
            j = i - 1
            while j >= 0 and counts[j] is None:
                j -= 1
            if j >= 0:
                counts[i] = counts[j]
            else:
                counts[i] = int(round(base_v1)) if base_v1 > 0 else 1
    # ensure non-decreasing
    for i in range(1, len(counts)):
        if counts[i] < counts[i - 1]:
            counts[i] = counts[i - 1]
    # clamp
    for i in range(len(counts)):
        if counts[i] < 0:
            counts[i] = 0
        if counts[i] > 1000000000:
            counts[i] = 1000000000
    return counts  # type: ignore


def forecast_hours(data: Dict[str, Any]) -> Dict[str, Any]:
    known = data.get("known")
    comparables = data.get("comparables")

    base_v1 = 0.0
    if isinstance(known, list) and len(known) > 0:
        v1_found = None
        for item in known:
            if isinstance(item, dict) and item.get("hour") == 1:
                v1_found = parse_viewers(item.get("viewers"))
                break
        if v1_found is None and isinstance(known[0], dict):
            v1_found = parse_viewers(known[0].get("viewers"))
        if v1_found is not None and v1_found > 0:
            base_v1 = float(v1_found)
        else:
            base_v1 = 0.0
    else:
        base_v1 = 0.0

    comps_list: List[Dict[str, Any]] = []
    if isinstance(comparables, list):
        for c in comparables:
            if isinstance(c, dict):
                comps_list.append(c)

    samples_by_hour = build_log_ratio_samples(comps_list)
    qs = [0.05, 0.25, 0.50, 0.75, 0.95]
    hours_out = []
    all_samples: List[Tuple[float, float]] = []
    for h in range(2, 25):
        all_samples.extend(samples_by_hour.get(h, []))

    for h in range(2, 25):
        samples = samples_by_hour.get(h, [])
        if len(samples) == 0:
            samples = all_samples[:]
        if len(samples) == 0:
            log_qs = [0.0, 0.0, 0.0, 0.0, 0.0]
        else:
            log_qs = weighted_quantiles(samples, qs)
            log_qs = [0.0 if (x != x or math.isinf(x)) else x for x in log_qs]
        # compute counts
        if base_v1 > 0:
            q_counts = clamp_and_round_q(log_qs, base_v1)
        else:
            # Non-positive known counts => produce valid strictly positive quantiles, never zero
            # Use ratio baseline 1.0 scaled to at least 1
            q_counts = clamp_and_round_q([0.0, 0.0, 0.0, 0.0, 0.0], 1.0)
        # enforce strictly positive and increasing, clamp 1..1e9
        for i in range(len(q_counts)):
            if q_counts[i] < 1:
                q_counts[i] = 1
            if q_counts[i] > 1000000000:
                q_counts[i] = 1000000000
        for i in range(1, len(q_counts)):
            if q_counts[i] < q_counts[i - 1]:
                q_counts[i] = q_counts[i - 1]
        hours_out.append({"hour": h, "q": q_counts})
    return {"hours": hours_out}


def main() -> None:
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass

    in_pattern = os.path.join(in_dir, "*.in")
    in_files = sorted(glob(in_pattern))
    if not in_files:
        return

    for fp in in_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        try:
            result = forecast_hours(data if isinstance(data, dict) else {})
        except Exception:
            # error fallback must produce valid strictly positive quantiles
            result = {"hours": [{"hour": h, "q": [1, 1, 1, 1, 1]} for h in range(2, 25)]}
        base_name = os.path.basename(fp)
        if base_name.endswith(".in"):
            out_name = base_name[:-3] + ".out"
        else:
            out_name = base_name + ".out"
        out_path = os.path.join(out_dir, out_name)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, separators=(",", ":"))
        except Exception:
            pass


if __name__ == "__main__":
    main()
