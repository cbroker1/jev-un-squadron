"""Prepare and review Choice inputs from captured evidence. API calls are impossible here.

No HTTP client, key reader, emulator launcher or controller writer is imported.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import uuid

from brain.combat import combat_digest, combat_request
from brain.observations import FamilyTracker, TableTracker, captures, observation
from brain.digest import ACTIONS, summarize
from brain.questions import movement_request

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--at-sample", type=int, default=620, help="sample to show in the readable summary")
    ap.add_argument("--horizon-frames", type=int, default=20)
    ap.add_argument("--mock-choice", choices=list(ACTIONS), help="optional explicitly labelled test choice; never applied")
    ap.add_argument("--combat", action="store_true", help="checked aircraft + projectile slots and the combat request builder")
    args = ap.parse_args()
    capture = args.capture.resolve()
    group = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = ROOT / "runs" / ("brain-replay-" + group)
    # Validate evidence before creating the output directory.
    frames = iter(captures(capture))
    first = next(frames)
    output.mkdir()
    tracker = TableTracker() if args.combat else FamilyTracker()
    import itertools
    selected = None
    count = 0
    with (output / "replay.jsonl").open("w", encoding="utf-8") as log:
        for row, raw in itertools.chain([first], frames):
            obs = observation(raw, row, capture.name, tracker)
            if args.combat:
                obs["coverage"] = "object-table helicopters, bullets, power-ups and tanks; other hazards unknown"
                digest = combat_digest(obs, args.horizon_frames)
                request = combat_request(digest)
            else:
                digest = summarize(obs, args.horizon_frames)
                request = movement_request(digest)
            record = {"run_id": output.name, "observed_state": obs, "projection": digest,
                      "request_preview": request, "decision_source": "deterministic_test" if args.mock_choice else "not_requested",
                      "requested_action": args.mock_choice, "applied_action": None,
                      "jev_requests": 0, "emulator_frames_advanced": 0}
            log.write(json.dumps(record) + "\n")
            if obs["sample"] == args.at_sample:
                selected = record
            count += 1
    if selected is None:
        raise ValueError("Requested summary sample was not captured; replay log was preserved")
    (output / "request_preview.json").write_text(json.dumps(selected["request_preview"], indent=2) + "\n", encoding="utf-8")
    obs, digest = selected["observed_state"], selected["projection"]
    lines = ["# Offline Jev-brain preview", "", f"Source: `{capture.name}`, sample {obs['sample']}, game frame {obs['source_frame']}.", "",
             "**No Jev request was made. No controller input was applied. These are projections, not observed outcomes.**", "",
             "| Action | What the Choice option says | Closest projected RAM-anchor gap | Aircraft-reference gap |",
             "|---|---|---|---|"]
    for action, value in digest["actions"].items():
        distance = value["closest_anchor_distance_px"]
        gap = "unknown" if distance is None else f"{distance:.1f} px (not collision clearance)"
        body = value.get("enemy_body_anchor_gap_px")
        body = "not computed (projectile preview)" if not args.combat else "unknown" if body is None else f"{body:.1f} px (not collision clearance)"
        lines.append(f"| {action} | {value['description']} | {gap} | {body} |")
    lines += ["", "Unknown: " + "; ".join(digest["unknowns"]) + ".", "",
              "The forecast uses measured cardinal speed, measured movement limits for this save, and recent projectile velocity. It does not simulate collisions.", "",
              f"Mock choice: `{args.mock_choice or 'none'}`; source: `{selected['decision_source']}`; applied input: **none**.", "",
              "The request file is a preview only. This tool never reads your credential file, calls an API, or writes runtime_action.json."]
    (output / "SUMMARY.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps({"source_capture": str(capture), "records": count,
        "at_sample": args.at_sample, "horizon_frames": args.horizon_frames, "combat": args.combat, "jev_requests": 0,
        "controller_writes": 0, "live_control_ready": False}, indent=2)+"\n", encoding="utf-8")
    print(f"Prepared {count} evidence-backed previews. Jev calls: 0. Controller writes: 0.")
    print(output / "SUMMARY.md")


if __name__ == "__main__":
    main()
