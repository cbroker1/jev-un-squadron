"""Build a measured terrain map from runs: where the aircraft flew safely, and where it hit.

Terrain is not in the object table, but the level scrolls deterministically and
`scroll_x` (WRAM 0x007B) gives the level position, so a frame's level column is
player_x + scroll_x. For each column this records the lowest altitude actually flown
without an untracked hit, and the altitude of any hit that had no tracked cause.

Measurement only: no emulator, no API. Columns with no observation stay unknown.
"""
import argparse
import json
from pathlib import Path

from brain.observations import RECORD_BYTES, TABLE_BASES, classify_record, fixed24

# Our own shots, $04:E6AF, travel right at exactly 11 px per frame. One that stops before
# the screen edge with no classified target beside it has hit something solid, which maps
# structures densely from ordinary runs instead of one column per collision taken.
PLAYER_SHOT = bytes.fromhex("afe604")
SHOT_EDGE_X = 235          # beyond this a shot is leaving the screen, not stopping
NEAR_A_TARGET_PX = 14
# When a shot destroys something the game spawns this marker where it died. A stop with no
# marker beside it hit terrain instead, which separates the two far better than proximity
# to a classified object: over 15 runs, stops with a marker were 42% near the ground and
# stops without were 90%, matching what structures look like.
DESTROYED_MARKER = bytes.fromhex("c0fc04")      # $04:FCC0
MARKER_WINDOW_FRAMES = 3
MARKER_NEAR_PX = 20
# A cell was only ever cleared at its exact altitude while the firing rule blocked a band
# around it, so a structure recorded at Y 176 kept blocking shots that fly freely at 177:
# 29.6% of shots that actually killed something would have been refused. Clearing over the
# same band the rule uses keeps the two consistent.
# Measured on 203 shots that killed and 172 that hit terrain: clearing over 4 px leaves
# 19 columns and catches 15.7% of walls for 2.0% false refusals, while clearing over 2 px
# leaves 24 columns and catches 22.1% for 6.4%. More walls caught matters here - Carl has
# watched shots go into structures three times - and 6.4% is far from the 30% that made
# the aircraft stop attacking in R33.
PASS_CLEARANCE_PX = 2
# A shot also stops against an enemy this code cannot classify yet, and those appear at any
# altitude, which made the first version of this map mark 37 altitudes in one column. The
# level is deterministic, so a real structure stops shots at the same place in run after
# run while an enemy hit does not: keep only what two separate runs both found.
# Repetition is the real discriminator, not how many runs saw it: a structure stops shots
# again and again as the aircraft passes, while an unclassified enemy is hit once. Measured
# over every run: 2 stops gives 23 columns at 92% near the ground, 3 gives 11 at 97%, 5
# gives 8 at 100%. Taking stops in separate runs OR enough stops overall keeps the columns
# that matter without the mid-air noise that made an earlier version block 74% of options.
# With the marker filter doing the separating, a single unpassed stop is already good
# evidence; requiring repetition on top of it only threw away coverage.
RUNS_THAT_MUST_AGREE = 1
STOPS_THAT_MUST_AGREE = 1

BUCKET = 4
# WRAM 0x007B counts the level scroll, but it wraps once the level stops scrolling at the
# boss (0..65529 observed in the run that reached it), so it is not a level position there.
# Those samples would land in columns of their own and be measured as if they were terrain.
MAX_PLAUSIBLE_SCROLL = 60000


def shot_samples(run):
    """("stop"|"pass", level column, altitude) for our own shots.

    A stop with no destroyed marker beside it hit terrain; one with a marker killed
    something. A shot that flies through the same cell is evidence it is open and
    outweighs any stop there, because an unclassified enemy can die anywhere.

    Each shot is followed as a trajectory: its own final sample sits inside the column
    where it stopped, and counting that as a pass cancelled every stop in the map.
    """
    flying, pending = {}, []
    for line in (run / "states.jsonl").read_text().splitlines():
        state = json.loads(line)["state"]
        table = state.get("observation_profile", {}).get("object_table")
        scroll = state.get("scroll_x")
        if not table or scroll is None or scroll > MAX_PLAUSIBLE_SCROLL:
            flying, pending = {}, []
            continue
        frame = state["frame"]
        data = bytes.fromhex(table["bytes_hex"])
        live, markers = {}, []
        for index, base in enumerate(TABLE_BASES):
            record = data[index*RECORD_BYTES:(index+1)*RECORD_BYTES]
            x, y = fixed24(record, 16), fixed24(record, 19)
            if bytes(record[1:4]) == PLAYER_SHOT and record[0] & 0x40:
                live[base] = (x, y, scroll)
            elif bytes(record[1:4]) == DESTROYED_MARKER:
                markers.append((x, y))
        # A stop is only terrain once no marker has appeared beside it for a few frames.
        for entry in pending[:]:
            x, y, at, column = entry
            if any(abs(x-mx) < MARKER_NEAR_PX and abs(y-my) < MARKER_NEAR_PX for mx, my in markers):
                pending.remove(entry)                  # it killed something
            elif frame-at > MARKER_WINDOW_FRAMES:
                pending.remove(entry)
                yield "stop", column, round(y)
        for base, track in list(flying.items()):
            if base in live:
                continue
            x, y, shot_scroll = track[-1]
            for px, py, ps in track[:-1]:
                yield "pass", int((px+ps)//BUCKET), round(py)
            if x < SHOT_EDGE_X:
                pending.append((x, y, frame, int((x+shot_scroll)//BUCKET)))
            else:
                yield "pass", int((x+shot_scroll)//BUCKET), round(y)
            del flying[base]
        for base, sample in live.items():
            if base in flying and sample[0] < flying[base][-1][0]:
                for px, py, ps in flying[base]:
                    yield "pass", int((px+ps)//BUCKET), round(py)
                flying[base] = []
            flying.setdefault(base, []).append(sample)


def run_samples(run):
    """(level column, player y, was this frame an untracked hit) for one run."""
    trace = run / "decision_trace.json"
    terrain_hits = set()
    if trace.exists():
        events = json.loads(trace.read_text()).get("candidate_table_events") or {}
        terrain_hits = {c["frame"] for c in events.get("hit_causes", []) if c["likely"] == "unidentified"}
    for line in (run / "states.jsonl").read_text().splitlines():
        state = json.loads(line)["state"]
        scroll = state.get("scroll_x")
        if scroll is None:
            return
        if scroll > MAX_PLAUSIBLE_SCROLL:      # the scroll wrapped; level position is unknown
            continue
        yield ("player", (state["player_x_candidate"]+scroll)//BUCKET,
               state["player_y_candidate"], state["frame"] in terrain_hits)
        # Tanks and turrets stand on the terrain, so they measure its surface wherever they appear.
        table = state.get("observation_profile", {}).get("object_table")
        if not table:
            continue
        data = bytes.fromhex(table["bytes_hex"])
        for index, base in enumerate(TABLE_BASES):
            record = data[index*RECORD_BYTES:(index+1)*RECORD_BYTES]
            kind, gated = classify_record(record)
            if gated and kind in ("ground_tank", "turret"):
                yield ("ground", int(fixed24(record, 16)+scroll)//BUCKET, fixed24(record, 19), False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--out", type=Path, default=Path("terrain_map.json"))
    args = ap.parse_args()
    # A column is not a floor: at level column 1644 a collision was recorded at Y 171 while
    # Y 189 was flown safely, so these are structures with open air below them. Keep every
    # measured altitude rather than collapsing them into a floor that was never observed.
    safe, hits, surface, used, bands, blocked, seen, passed = {}, {}, {}, [], {}, {}, {}, set()
    repeats = {}
    for run in sorted(args.runs.glob("combat-*")):
        if not (run / "states.jsonl").exists():
            continue
        count = 0
        for source, column, y, was_hit in run_samples(run) or ():
            count += 1
            if source == "ground":
                surface[column] = min(surface.get(column, 999), y)
            elif was_hit:
                hits[column] = min(hits.get(column, 999), y)
                bands.setdefault(column, set()).add(round(y))
            else:
                safe[column] = max(safe.get(column, 0), y)
        for what, column, y in shot_samples(run):
            if what == "stop":
                seen.setdefault((column, y), set()).add(run.name)
                repeats[(column, y)] = repeats.get((column, y), 0)+1
            else:
                for near in range(y-PASS_CLEARANCE_PX, y+PASS_CLEARANCE_PX+1):
                    passed.add((column, near))
        if count:
            used.append({"run": run.name, "frames": count})
    for (column, y), runs in seen.items():
        # Solid only where shots stopped repeatedly and none has ever flown through.
        if (column, y) in passed:
            continue
        if len(runs) >= RUNS_THAT_MUST_AGREE or repeats.get((column, y), 0) >= STOPS_THAT_MUST_AGREE:
            blocked.setdefault(column, set()).add(y)
    columns = sorted(set(safe) | set(hits) | set(surface) | set(blocked))
    payload = {"status": "measured: lowest altitude flown without an untracked hit, and untracked-hit altitudes",
               "bucket_px": BUCKET, "scroll_address": "0x007B", "runs": used,
               "level_column_range": [columns[0]*BUCKET, columns[-1]*BUCKET] if columns else None,
               "columns": {str(c): {"safe_max_y": safe.get(c), "hit_min_y": hits.get(c),
                                    "collision_altitudes": sorted(bands.get(c, ())) or None,
                                    "shots_stopped_at": sorted(blocked.get(c, ())) or None,
                                    "ground_object_y": round(surface[c], 1) if c in surface else None} for c in columns}}
    args.out.write_text(json.dumps(payload, separators=(",", ":"))+"\n")
    print(json.dumps({"runs_used": len(used), "columns": len(columns),
                      "columns_with_hits": len(hits), "columns_with_ground_objects": len(surface),
                      "columns_where_shots_stopped": len(blocked),
                      "level_range": payload["level_column_range"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
