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

BUCKET = 4


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
    safe, hits, surface, used = {}, {}, {}, []
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
            else:
                safe[column] = max(safe.get(column, 0), y)
        if count:
            used.append({"run": run.name, "frames": count})
    columns = sorted(set(safe) | set(hits) | set(surface))
    payload = {"status": "measured: lowest altitude flown without an untracked hit, and untracked-hit altitudes",
               "bucket_px": BUCKET, "scroll_address": "0x007B", "runs": used,
               "level_column_range": [columns[0]*BUCKET, columns[-1]*BUCKET] if columns else None,
               "columns": {str(c): {"safe_max_y": safe.get(c), "hit_min_y": hits.get(c),
                                    "ground_object_y": round(surface[c], 1) if c in surface else None} for c in columns}}
    args.out.write_text(json.dumps(payload, separators=(",", ":"))+"\n")
    print(json.dumps({"runs_used": len(used), "columns": len(columns),
                      "columns_with_hits": len(hits), "columns_with_ground_objects": len(surface),
                      "level_range": payload["level_column_range"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
