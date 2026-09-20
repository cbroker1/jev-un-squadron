"""Measure where the aircraft has actually been dying, per level position and altitude.

The terrain map only learns from a collision taken or a shot stopped, which covers a few
dozen columns. Every frame of every run is evidence of something else: the aircraft was
here, at this altitude, and either lived or was destroyed shortly afterwards. Aggregated
over the runs, that gives a dense measured picture of where the stage is dangerous,
covering structures, gun emplacements and crossfire alike without naming any of them.

This is measurement, not a rule: cells with few samples are reported as unknown, and
nothing here says what to do about a dangerous cell.

Offline only: no emulator, no API.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

COLUMN_PX = 8          # level position bucket
ALTITUDE_PX = 8        # altitude bucket
DOOMED_FRAMES = 60     # a death within a second of being here counts against the cell
HURT_FRAMES = 30       # a hit taken within half a second counts too, and hits are commoner
MIN_SAMPLES = 25       # below this a cell stays unknown rather than guessing from noise
MAX_PLAUSIBLE_SCROLL = 60000


def run_track(run):
    """Every frame's cell, the frame the run died on, and the frames it was hit on.

    A run yields one death but several hits, so hits are the denser signal about where
    the stage hurts; both are counted, separately, because they are different evidence.
    """
    samples, died, hurt = [], None, []
    trace = run / "decision_trace.json"
    if trace.exists():
        try:
            events = json.loads(trace.read_text()).get("candidate_table_events") or {}
            hurt = sorted(events.get("hit_marker_frames") or [])
        except ValueError:
            hurt = []
    summary = run / "summary.json"
    if summary.exists():
        report = json.loads(summary.read_text())
        if report.get("reason") in ("player_object_destroyed", "player_reference_outside_validated_bounds"):
            died = report.get("final_frame")
    for line in (run / "states.jsonl").read_text().splitlines():
        state = json.loads(line).get("state") or {}
        scroll = state.get("scroll_x")
        if scroll is None or scroll > MAX_PLAUSIBLE_SCROLL:
            continue
        x, y = state.get("player_x_candidate"), state.get("player_y_candidate")
        if x is None or y is None or not (0 < x < 256 and 0 < y < 224):
            continue
        samples.append(((x+scroll)//COLUMN_PX, y//ALTITUDE_PX, state["frame"]))
    return samples, died, hurt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--out", type=Path, default=Path("danger_map.json"))
    args = ap.parse_args()
    flown, doomed, hurt_soon, used = defaultdict(int), defaultdict(int), defaultdict(int), 0
    for run in sorted(args.runs.glob("combat-*")):
        if not (run / "states.jsonl").exists():
            continue
        samples, died, hurt = run_track(run)
        if not samples:
            continue
        used += 1
        for column, altitude, frame in samples:
            flown[(column, altitude)] += 1
            if died is not None and 0 <= died-frame <= DOOMED_FRAMES:
                doomed[(column, altitude)] += 1
            if any(0 <= at-frame <= HURT_FRAMES for at in hurt):
                hurt_soon[(column, altitude)] += 1
    cells = {f"{column},{altitude}": {"frames": flown[(column, altitude)],
                                      "deaths_soon_after": doomed[(column, altitude)],
                                      "hits_soon_after": hurt_soon[(column, altitude)]}
             for column, altitude in flown if flown[(column, altitude)] >= MIN_SAMPLES}
    payload = {"status": f"measured: frames flown in each cell, how many preceded a death within "
                         f"{DOOMED_FRAMES} frames, and how many preceded a hit within {HURT_FRAMES}",
               "hurt_window_frames": HURT_FRAMES,
               "column_px": COLUMN_PX, "altitude_px": ALTITUDE_PX,
               "doomed_window_frames": DOOMED_FRAMES, "minimum_samples": MIN_SAMPLES,
               "runs_used": used, "cells": cells}
    args.out.write_text(json.dumps(payload, separators=(",", ":"))+"\n")
    risky = sorted(cells.items(), key=lambda kv: -kv[1]["deaths_soon_after"]/kv[1]["frames"])[:8]
    print(json.dumps({"runs_used": used, "cells": len(cells),
                      "cells_with_a_death": sum(1 for c in cells.values() if c["deaths_soon_after"]),
                      "most_dangerous": [{"cell": k, "frames": v["frames"],
                                          "deaths": v["deaths_soon_after"]} for k, v in risky],
                      "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
