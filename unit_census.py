"""How many units a run met, and how many of them it destroyed.

Kills alone cannot say how close a run is to clearing a stage: 70 kills is either
excellent or half the job depending on what came past. Every target the object table
ever showed is counted here, by kind and by where in the level it appeared, against the
ones destroyed, so the gap is visible and has a position.

A unit is one continuous tracked lifetime - a slot plus the tracker's generation for it -
which is the same identity the controller uses. Offline only: no emulator, no API.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from brain.observations import RECORD_BYTES, TABLE_BASES, TableTracker

TARGETS = ("enemy_aircraft", "ground_tank", "turret", "boss_part")
DESTROYED_EVENTS = {"enemy_aircraft": "aircraft_destroyed", "ground_tank": "tanks_destroyed",
                    "turret": "turrets_destroyed"}
SEGMENT_PX = 256        # report the level in screen-widths, so a gap can be found


def census(run, from_frame=0):
    """(units met by kind, units met by level segment, kills by kind) for one run."""
    tracker = TableTracker()
    met, where, seen = Counter(), defaultdict(Counter), set()
    for line in (run / "states.jsonl").read_text().splitlines():
        state = json.loads(line).get("state") or {}
        table = (state.get("observation_profile") or {}).get("object_table")
        if not table or state["frame"] < from_frame:
            continue
        data = bytes.fromhex(table["bytes_hex"])
        records = {base: data[i*RECORD_BYTES:(i+1)*RECORD_BYTES] for i, base in enumerate(TABLE_BASES)}
        scroll = state.get("scroll_x")
        for track in tracker.observe_records(records, state["frame"], state.get("lua_session_id", ""),
                                             state.get("reload_epoch", 0)):
            if track["kind"] not in TARGETS or not track.get("in_play"):
                continue
            identity = (track["slot"], track["generation"])
            if identity in seen:
                continue
            seen.add(identity)
            met[track["kind"]] += 1
            if scroll is not None and scroll <= 60000:
                where[int((track["x"]+scroll)//SEGMENT_PX)][track["kind"]] += 1
    kills = Counter()
    trace = run / "decision_trace.json"
    if trace.exists():
        try:
            events = json.loads(trace.read_text()).get("candidate_table_events") or {}
        except ValueError:
            events = {}
        for kind, name in DESTROYED_EVENTS.items():
            kills[kind] = len([e for e in events.get(name, []) if e["frame"] >= from_frame])
    return met, where, kills


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--from-frame", type=int, default=20663, help="when Jev takes control")
    args = ap.parse_args()
    met, where, kills = census(args.run, args.from_frame)
    total_met = sum(met.values())
    total_killed = sum(kills.values())
    print(f"{args.run.name}")
    print(f"{'kind':16} {'met':>5} {'destroyed':>10} {'share':>7}")
    for kind in TARGETS:
        share = f"{kills[kind]/met[kind]:.0%}" if met[kind] else "-"
        print(f"{kind:16} {met[kind]:>5} {kills[kind]:>10} {share:>7}")
    print(f"{'total':16} {total_met:>5} {total_killed:>10} "
          f"{(total_killed/total_met if total_met else 0):>7.0%}")
    print("\nunits met per screen-width of level (where the misses would be):")
    for segment in sorted(where):
        counts = where[segment]
        print(f"  {segment*SEGMENT_PX:>6}-{(segment+1)*SEGMENT_PX:<6} px: "
              + ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in counts.most_common()))


if __name__ == "__main__":
    main()
