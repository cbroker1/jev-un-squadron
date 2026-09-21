"""Regression check for gameplay, not code: has a change made an earlier part worse?

Offline tests cover the measurements; nothing covered the play. Work concentrated on the
second half of the stage for a day, and the fair question was whether the first half had
quietly rotted. This answers that with numbers: every run is scored per segment of the
level, and the newest runs are compared against the band the previous ones established.

A segment's result only counts when a run actually flew through it, so dying early lowers
coverage rather than faking a low score.

Offline only: no emulator, no API.
"""
import argparse
import json
import statistics
from pathlib import Path

DECISION_START = 20663
SEGMENTS = {"opening": (20663, 21400),        # first wave, first tanks
            "middle": (21400, 22200),          # helicopter waves, power-ups
            "fortified line": (22200, 23400),  # gun emplacements, the structures
            "approach": (23400, 24040),        # the run-up to the boss
            "boss": (24040, 26000)}
DESTROYED = ("aircraft_destroyed", "tanks_destroyed", "turrets_destroyed", "boss_parts_destroyed")


def entry_kind(start):
    if not start:
        return "unstarted"
    # Early full-level runs started a few frames later while waiting for tracks.
    if start < 21000:
        return "full"
    return "boss" if start >= 24000 else "practice"


def score(run):
    """Per-segment kills and hits for one run, for the segments it actually flew."""
    try:
        events = json.loads((run / "decision_trace.json").read_text())["candidate_table_events"]
        if not isinstance(events, dict):          # a run that died before anything was traced
            return None
        summary = json.loads((run / "summary.json").read_text())
        label = json.loads((run / "manifest.json").read_text()).get("run_label")
    except (OSError, ValueError, KeyError):
        return None
    start, end = summary.get("first_request_frame"), summary.get("final_frame")
    if not start or not end:
        return None
    out = {"run": label, "started": start, "ended": end, "segments": {}}
    for name, (low, high) in SEGMENTS.items():
        begin = max(start, low)
        if begin >= high or end <= begin:
            continue
        reached = min(end, high)
        kills = sum(len([e for e in events.get(field, []) if begin <= e["frame"] <= reached and e["frame"] < high])
                    for field in DESTROYED)
        hits = len([f for f in events.get("hit_marker_frames", []) if begin <= f <= reached and f < high])
        out["segments"][name] = {"kills": kills, "hits": hits,
                                 "frames": reached-begin, "complete": start <= low and end >= high}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--recent", type=int, default=3, help="how many newest runs to judge")
    ap.add_argument("--baseline", type=int, default=12, help="how many runs form the band")
    ap.add_argument("--entry", choices=("full", "boss", "practice"), default="full",
                    help="compare runs from the same entry (default: full level)")
    args = ap.parse_args()
    if args.recent < 1 or args.baseline < 3:
        ap.error("recent must be positive and baseline at least 3")
    scored, missing = [], []
    for run in sorted(args.runs.glob("combat-*live")):
        try:
            summary = json.loads((run / "summary.json").read_text())
            label = json.loads((run / "manifest.json").read_text()).get("run_label")
        except (OSError, ValueError):
            continue
        if entry_kind(summary.get("first_request_frame")) != args.entry:
            continue
        result = score(run)
        if result:
            scored.append(result)
        else:
            missing.append(label or run.name)
    if missing:
        print(f"WARNING: {len(missing)} {args.entry} runs have missing/invalid analysis: {missing}")
    scored.sort(key=lambda s: s["run"] or 0)
    if len(scored) < args.recent+3:
        raise SystemExit("not enough scored runs yet")
    recent, earlier = scored[-args.recent:], scored[-(args.recent+args.baseline):-args.recent]
    print(f"entry={args.entry}: judging runs {[s['run'] for s in recent]} "
          f"against runs {[s['run'] for s in earlier]}\n")
    print(f"{'segment':>16} {'baseline kills':>15} {'recent kills':>13} {'baseline hits':>14} "
          f"{'recent hits':>12}  verdict")
    worse = []
    for name in SEGMENTS:
        was = [s["segments"][name]["kills"] for s in earlier if name in s["segments"]]
        now = [s["segments"][name]["kills"] for s in recent if name in s["segments"]]
        was_hits = [s["segments"][name]["hits"] for s in earlier if name in s["segments"]]
        now_hits = [s["segments"][name]["hits"] for s in recent if name in s["segments"]]
        if len(was) < 3 or not now:
            print(f"{name:>16} {'-':>15} {'-':>13} {'-':>14} {'-':>12}  not enough runs")
            continue
        floor = statistics.mean(was) - statistics.pstdev(was)
        verdict = "ok"
        if statistics.mean(now) < floor:
            verdict = "WORSE on kills"
            worse.append(name)
        elif was_hits and statistics.mean(now_hits) > statistics.mean(was_hits)+1:
            verdict = "worse on damage"
        print(f"{name:>16} {statistics.mean(was):>15.1f} {statistics.mean(now):>13.1f} "
              f"{statistics.mean(was_hits):>14.1f} {statistics.mean(now_hits):>12.1f}  {verdict}")
        before_frames = [s["segments"][name]["frames"] for s in earlier if name in s["segments"]]
        after_frames = [s["segments"][name]["frames"] for s in recent if name in s["segments"]]
        partial = any(not s["segments"][name]["complete"] for s in earlier+recent if name in s["segments"])
        if partial:
            print(f"  partial coverage: observed frames {statistics.mean(before_frames):.0f} -> "
                  f"{statistics.mean(after_frames):.0f}; raw kills depend on time survived")
    print("\n" + ("regression in: " + ", ".join(worse) if worse else "no segment is below its baseline band"))


if __name__ == "__main__":
    main()
