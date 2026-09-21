"""Join observations, typed decisions and core input readback. No game/API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from brain.digest import ACTIONS, player_position
from brain.observations import RECORD_BYTES, TABLE_BASES, classify_record, fixed24

HIT_MARKER = (0x1040, bytes.fromhex("a1f804"))  # $04:F8A1 appears in 0x1040 when the player is hit (candidate)
EXPLODING = bytes.fromhex("c0fc04")              # $04:FCC0 follows a destroyed object
SPENT_BULLET = bytes.fromhex("c3f904")           # $04:F9C3 follows a bullet that has struck


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def table_events(states):
    """Candidate outcome events from the exported object table; not a health or scoring decoder."""
    events = {"hit_marker_frames": [], "power_up_gone_near_player": [], "power_up_gone_elsewhere": [],
              "tanks_destroyed": [], "aircraft_destroyed": [], "turrets_destroyed": [],
              "boss_parts_destroyed": [], "hit_causes": []}
    previous = None
    for frame in sorted(states):
        state = states[frame]["state"]
        table = state.get("observation_profile", {}).get("object_table")
        if not table:
            return None
        data = bytes.fromhex(table["bytes_hex"])
        records = {b: data[i*RECORD_BYTES:(i+1)*RECORD_BYTES] for i, b in enumerate(TABLE_BASES)}
        px, py = state["player_x_candidate"], state["player_y_candidate"]
        if previous:
            base, routine = HIT_MARKER
            if records[base][1:4] == routine and previous[base][1:4] != routine:
                events["hit_marker_frames"].append(frame)
                # On a collision the other object flips state in the same frame, so name
                # what it was one frame earlier. Candidate attribution, not a damage model.
                causes = []
                for slot in TABLE_BASES:
                    kind, was_gated = classify_record(previous[slot])
                    if not was_gated or slot in (base, 0x1000):
                        continue
                    changed = records[slot][1:4] in (EXPLODING, SPENT_BULLET) or not classify_record(records[slot])[1]
                    x, y = fixed24(previous[slot], 16), fixed24(previous[slot], 19)
                    distance = ((x-px)**2+(y-py)**2)**0.5
                    if changed and distance <= 40:
                        causes.append({"kind": kind, "distance_px": round(distance, 1), "xy": [round(x, 1), round(y, 1)]})
                events["hit_causes"].append({"frame": frame, "player_xy": [px, py],
                                             "likely": sorted(causes, key=lambda c: c["distance_px"])[:2] or "unidentified"})
            for b in TABLE_BASES:
                kind, gated = classify_record(previous[b])
                x, y = fixed24(previous[b], 16), fixed24(previous[b], 19)
                if kind in ("power_up", "clear_screen_power_up") and gated and classify_record(records[b]) != (kind, True):
                    near = ((x-px)**2+(y-py)**2)**0.5 <= 24
                    events["power_up_gone_near_player" if near else "power_up_gone_elsewhere"].append(
                        {"frame": frame, "kind": kind, "power_up_xy": [round(x, 1), round(y, 1)], "player_xy": [px, py]})
                if kind in ("ground_tank", "enemy_aircraft", "turret", "boss_part") and gated                         and records[b][1:4] == EXPLODING:
                    field = {"ground_tank": "tanks_destroyed", "enemy_aircraft": "aircraft_destroyed",
                             "turret": "turrets_destroyed", "boss_part": "boss_parts_destroyed"}[kind]
                    events[field].append({"frame": frame, "target_xy": [round(x, 1), round(y, 1)], "player_xy": [px, py]})
        previous = records
    return events


def analyze(run, baseline=None):
    events=read_lines(run / "events.jsonl")
    result=json.loads((run / "validation.json").read_text())
    states={r["state"]["frame"]:r for r in read_lines(run / "states.jsonl")}
    actions={a["command_id"]:a for a in result["actions"]}
    responses={e["attempt"]:e for e in events if e["event"]=="response"}
    acks={e["attempt"]:e for e in events if e["event"]=="input_ack" and e["attempt"] is not None}
    commands={e["command"]["attempt"]:e["command"] for e in events if e["event"]=="command" and e["command"]["attempt"] is not None}
    trace=[]
    for request in (e for e in events if e["event"] in ("request","mock_request")):
        attempt=request["attempt"]
        response,ack,command=responses.get(attempt),acks.get(attempt),commands.get(attempt)
        actual=actions.get(command["call"]) if command else None
        entry={"attempt":attempt,"source":"jev" if request["event"]=="request" else "deterministic_mock",
            "observed_frame":request["observed_state"]["frame"],
            "observed_player_xy":[request["observation"]["player"][axis] for axis in ("x","y")],
            "known_tracks":request["request_body"]["state"]["known_tracks"],
            "request_interval_frames":request["interval_since_previous_request_frames"],
            "requested_action":response["response"]["choice"] if response else None,
            "raw_choice":response["response"].get("raw_choice") if response else None,
            "selection_reason":response["response"].get("selection_reason") if response else None,
            "objective":response["response"].get("objective") if response else None,
            "decision_source":command.get("decision_source") if command else None,
            "response_latency_ms":response["latency_ms"] if response else None,
            "response_frame":response["received_frame"] if response else None,
            "observe_to_apply_frames":ack["observe_to_apply_frames"] if ack else None,
            "bridge_issue_to_apply_frames":ack["issue_to_apply_frames"] if ack else None,
            "actual":actual,"health_damage_death":None}
        if actual and actual["applied_frames"]:
            dx,dy=ACTIONS[actual["action"]]
            expected=player_position(*actual["start_xy"],dx,dy,actual["applied_frames"])
            entry["constant_speed_expected_end_xy"]=expected
            entry["end_xy_error_from_constant_speed"]=[round(a-b,3) for a,b in zip(actual["end_xy"],expected)]
            entry["screenshots"]=sorted(p.name for p in run.glob(f"frame_*_call_{actual['command_id']}.png"))
        trace.append(entry)
    latencies=[t["response_latency_ms"] for t in trace if t["response_latency_ms"] is not None]
    report={"run_id":run.name,"jev_requests":result["jev_requests"],"trace":trace,
        "median_response_ms":statistics.median(latencies) if latencies else None,
        "deterministic_controller_sources":sorted({a["source"] for a in actions.values() if a["source"]!="jev"}),
        "collision_avoidance_or_level_clear_proved":False,
        "candidate_table_events":table_events(states)}
    if baseline:
        other={r["state"]["frame"]:r for r in read_lines(baseline / "states.jsonl")}
        first=min((t["actual"]["first_apply_frame"] for t in trace if t["actual"]),default=0)
        common=sorted(set(states)&set(other))
        prefix=[f for f in common if f<=first]
        fields=("player_x_candidate","player_y_candidate","observation_profile")
        matched=sum(all(states[f]["state"][k]==other[f]["state"][k] for k in fields) for f in prefix)
        images=[p for p in run.glob("brain_frame_*.png") if int(p.stem.split("_")[-1])<=first and (baseline / p.name).exists()]
        image_matches=sum(hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256((baseline / p.name).read_bytes()).digest() for p in images)
        report["comparison"]={"baseline":baseline.name,"common_end_frame":max(common) if common else None,
            "predecision_matching_observations":matched,"predecision_compared_observations":len(prefix),
            "predecision_identical_screenshots":image_matches,"predecision_compared_screenshots":len(images),
            "baseline_end_player_xy":[other[max(common)]["state"][k] for k in ("player_x_candidate","player_y_candidate")] if common else None,
            "survival_damage_kills_pickups":None,
            "conclusion":"Matched-prefix check only; this does not establish survival or gameplay improvement."}
    (run / "decision_trace.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--baseline",type=Path)
    args=parser.parse_args()
    print(json.dumps(analyze(args.run,args.baseline),indent=2))
