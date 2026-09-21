"""The run table: what each run scored, and what change it was testing.

The goal is every unit on the level destroyed with the aircraft untouched, so the table
leads with the share of units killed and the number of times the plane was hit, and says
which change in approach each run was carrying. Runs without a recorded change are older
ones, before the column existed.

Offline only: no emulator, no API.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from brain.observations import FULL_HEALTH
from unit_census import census

DECISION_START = 20663


def row(run):
    try:
        manifest = json.loads((run / "manifest.json").read_text())
        summary = json.loads((run / "summary.json").read_text())
    except (OSError, ValueError):
        return None
    if summary.get("mode") != "live" or not summary.get("jev_requests"):
        return None
    if not (run / "decision_trace.json").exists():
        subprocess.run([sys.executable, "analyze_segment.py", str(run)], capture_output=True)
    try:
        events = json.loads((run / "decision_trace.json").read_text())["candidate_table_events"] or {}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(events, dict):
        return None
    start = summary.get("first_request_frame") or DECISION_START
    met, _, kills = census(run, start)
    total, killed = sum(met.values()), sum(kills.values())
    return {"run": manifest.get("run_label"), "change": manifest.get("change_under_test") or "",
            "from": start, "to": summary.get("final_frame"),
            "met": total, "killed": killed,
            "share": killed/total if total else 0,
            "hits": len(events.get("hit_marker_frames") or []),
            # Health is authoritative; the marker missed 6 of 33 damage events.
            "damage": sum(e["lost"] for e in (events.get("damage_events") or [])),
            "health_left": min([e["health_left"] for e in (events.get("damage_events") or [])],
                               default=FULL_HEALTH),
            "tanks": f"{kills['ground_tank']}/{met['ground_tank']}",
            "turrets": f"{kills['turret']}/{met['turret']}",
            "boss": f"{kills['boss_part']}/{met['boss_part']}",
            "ended": (summary.get("reason") or "").replace("player_object_destroyed", "died")
                                                 .replace("game_frame_budget", "ran out of frames")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--last", type=int, default=12)
    ap.add_argument("--full-level-only", action="store_true")
    args = ap.parse_args()
    rows = [r for r in (row(p) for p in sorted(args.runs.glob("combat-*live"))) if r and r["run"]]
    if args.full_level_only:
        rows = [r for r in rows if r["from"] <= DECISION_START]
    rows.sort(key=lambda r: r["run"])
    rows = rows[-args.last:]
    print(f"{'run':>4} {'units':>9} {'share':>6} {'damage':>7} {'left':>5} {'tanks':>7} {'turrets':>8} {'boss':>7} "
          f"{'to frame':>9} {'ended':>18}  change under test")
    for r in rows:
        print(f"R{r['run']:<3} {r['killed']:>4}/{r['met']:<4} {r['share']:>5.0%} {r['damage']:>7} "
              f"{r['health_left']:>5} "
              f"{r['tanks']:>7} {r['turrets']:>8} {r['boss']:>7} {r['to']:>9} {r['ended']:>18}  {r['change']}")
    if rows:
        best = max(rows, key=lambda r: r["share"])
        clean = [r for r in rows if r["damage"] == 0]
        print("")
        print(f"goal: 100% of units, no damage.  best here: R{best['run']} "
              f"losing {best['damage']} health; runs that took no damage: {len(clean)}/{len(rows)}")


if __name__ == "__main__":
    main()
