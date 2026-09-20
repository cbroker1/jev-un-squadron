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
# A shot also stops against an enemy this code cannot classify yet, and those appear at any
# altitude, which made the first version of this map mark 37 altitudes in one column. The
# level is deterministic, so a real structure stops shots at the same place in run after
# run while an enemy hit does not: keep only what two separate runs both found.
RUNS_THAT_MUST_AGREE = 2

BUCKET = 4
# WRAM 0x007B counts the level scroll, but it wraps once the level stops scrolling at the
# boss (0..65529 observed in the run that reached it), so it is not a level position there.
# Those samples would land in columns of their own and be measured as if they were terrain.
MAX_PLAUSIBLE_SCROLL = 60000


def shot_stops(run):
    """(level column, altitude) where a shot stopped against something solid."""
    previous = {}
    for line in (run / "states.jsonl").read_text().splitlines():
        state = json.loads(line)["state"]
        table = state.get("observation_profile", {}).get("object_table")
        scroll = state.get("scroll_x")
        if not table or scroll is None or scroll > MAX_PLAUSIBLE_SCROLL:
            previous = {}
            continue
        data = bytes.fromhex(table["bytes_hex"])
        live, targets = {}, []
        for index, base in enumerate(TABLE_BASES):
            record = data[index*RECORD_BYTES:(index+1)*RECORD_BYTES]
            kind, gated = classify_record(record)
            x, y = fixed24(record, 16), fixed24(record, 19)
            if gated and kind in ("enemy_aircraft", "ground_tank", "turret"):
                targets.append((x, y))
            if bytes(record[1:4]) == PLAYER_SHOT and record[0] & 0x40:
                live[base] = (x, y)
        for base, (x, y) in previous.items():
            if base in live or x >= SHOT_EDGE_X:
                continue
            if any(abs(x-tx) < NEAR_A_TARGET_PX and abs(y-ty) < NEAR_A_TARGET_PX for tx, ty in targets):
                continue                      # it hit something we can already see
            yield int((x+scroll)//BUCKET), round(y)
        previous = live


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
    safe, hits, surface, used, bands, blocked, seen = {}, {}, {}, [], {}, {}, {}
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
        for column, y in set(shot_stops(run)):
            seen.setdefault((column, y), set()).add(run.name)
        if count:
            used.append({"run": run.name, "frames": count})
    for (column, y), runs in seen.items():
        if len(runs) >= RUNS_THAT_MUST_AGREE:
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
