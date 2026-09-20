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


def score(run):
    """Per-segment kills and hits for one run, for the segments it actually flew."""
    try:
        events = json.loads((run / "decision_trace.json").read_text())["candidate_table_events"]
        summary = json.loads((run / "summary.json").read_text())
        label = json.loads((run / "manifest.json").read_text()).get("run_label")
    except (OSError, ValueError, KeyError):
        return None
    start, end = summary.get("first_request_frame"), summary.get("final_frame")
    if not start or not end:
        return None
    out = {"run": label, "started": start, "ended": end, "segments": {}}
    for name, (low, high) in SEGMENTS.items():
        if start > low or end < low+150:
            continue                       # never entered it, or entered and died at once
        reached = min(end, high)
        kills = sum(len([e for e in events.get(field, []) if low <= e["frame"] <= reached])
                    for field in DESTROYED)
        hits = len([f for f in events.get("hit_marker_frames", []) if low <= f <= reached])
        out["segments"][name] = {"kills": kills, "hits": hits,
                                 "frames": reached-low, "complete": end >= high}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--recent", type=int, default=3, help="how many newest runs to judge")
    ap.add_argument("--baseline", type=int, default=12, help="how many runs form the band")
    args = ap.parse_args()
    scored = [s for s in (score(r) for r in sorted(args.runs.glob("combat-*live"))) if s]
    scored.sort(key=lambda s: s["run"] or 0)
    if len(scored) < args.recent+3:
        raise SystemExit("not enough scored runs yet")
    recent, earlier = scored[-args.recent:], scored[-(args.recent+args.baseline):-args.recent]
    print(f"judging runs {[s['run'] for s in recent]} against the {len(earlier)} before them\n")
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
    print("\n" + ("regression in: " + ", ".join(worse) if worse else "no segment is below its baseline band"))


if __name__ == "__main__":
    main()
