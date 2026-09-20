"""Describe the investigated slot's transitions and match independent visual measurements.

This is evidence extraction, not automatic acceptance of an object/active-state map.
"""
import argparse
import csv
import json
from pathlib import Path

from brain.observations import SLOT, SlotTracker, captures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--discover-family", action="store_true", help="rank signature/layout candidates; never enable them for control")
    args = ap.parse_args()
    visual = {}
    path = args.capture / "cyan_components.csv"
    if path.exists():
        with path.open(newline="") as file:
            for row in csv.DictReader(file):
                if int(row["pixels"]) >= 4:
                    visual.setdefault(int(row["sample"]), []).append(row)
    if args.discover_family:
        candidates = {}
        for row, raw in captures(args.capture):
            data = bytes(raw)
            offset = 0
            while True:
                base = data.find(bytes.fromhex("cc7ff904"), offset)
                if base < 0:
                    break
                offset = base + 4
                if base+22 > len(data) or data[base+8] != 1:
                    continue
                # This relative layout is a candidate until visual comparisons support it.
                x = int.from_bytes(data[base+16:base+19], "little", signed=True)/256
                y = int.from_bytes(data[base+19:base+22], "little", signed=True)/256
                item = candidates.setdefault(f"0x{base:04X}", {"samples": 0, "on_screen_samples": 0, "matches": []})
                item["samples"] += 1
                if not (0 <= x < 256 and 0 <= y < 224):
                    continue
                item["on_screen_samples"] += 1
                near = [v for v in visual.get(int(row["sample"]), []) if abs(float(v["center_x"])-x) <= 3 and abs(float(v["center_y"])-y) <= 3]
                if len(near) == 1:
                    item["matches"].append({"sample": int(row["sample"]), "frame": int(row["emu_frame"]),
                                           "ram_xy": [x,y], "visual_xy": [float(near[0]["center_x"]),float(near[0]["center_y"])],
                                           "screenshot": row["screenshot"]})
        (args.capture / "signature_candidates.json").write_text(json.dumps({"status": "candidates only", "candidates": candidates}, indent=2)+"\n")
        print(json.dumps({base: {"samples": item["samples"], "on_screen": item["on_screen_samples"], "visual_matches": len(item["matches"])} for base, item in candidates.items()}, indent=2))
        return
    tracker = SlotTracker()
    generations, transitions, matches = {}, [], []
    last_signature = None
    for row, raw in captures(args.capture):
        sample, frame = int(row["sample"]), int(row["emu_frame"])
        track = tracker.observe(raw, frame, args.capture.name)
        signature = bytes(raw[SLOT:SLOT+16]).hex()
        if signature != last_signature:
            transitions.append({"sample": sample, "source_frame": frame, "header_hex": signature,
                                "x": track["x"], "y": track["y"], "phase": track["phase"]})
            last_signature = signature
        if track["phase"] != "observed_moving_signature":
            continue
        gen = generations.setdefault(track["generation"], {"first_sample": sample, "first_frame": frame,
                 "first_xy": [track["x"], track["y"]], "visual_match_count": 0, "offscreen_samples": 0,
                 "velocity_samples": []})
        gen.update(last_sample=sample, last_frame=frame, last_xy=[track["x"], track["y"]])
        if not track["on_screen"]:
            gen["offscreen_samples"] += 1
        if track["vx"] is not None:
            gen["velocity_samples"].append([track["vx"], track["vy"]])
        nearby = [v for v in visual.get(sample, []) if abs(float(v["center_x"])-track["x"]) <= 3
                  and abs(float(v["center_y"])-track["y"]) <= 3]
        if len(nearby) == 1:
            gen["visual_match_count"] += 1
            matches.append({"sample": sample, "source_frame": frame, "generation": track["generation"],
                "ram_xy": [track["x"], track["y"]], "visual_xy": [float(nearby[0]["center_x"]), float(nearby[0]["center_y"])],
                "pixels": int(nearby[0]["pixels"]), "screenshot": row["screenshot"]})
    for gen in generations.values():
        velocities = gen.pop("velocity_samples")
        gen["velocity_range"] = [[min(v[i] for v in velocities), max(v[i] for v in velocities)] for i in (0,1)] if velocities else None
    report = {"source_capture": args.capture.name, "status": "evidence only; general object semantics unverified",
              "notes": ["Missing cyan pixels are not proof of absence; sprite animation changes color.",
                        "Header transitions are observed bytes, not inferred game routine names.",
                        "Generation boundaries invalidate velocity; they do not identify every enemy bullet."],
              "generations": generations, "transitions": transitions, "visual_matches": matches, "jev_requests": 0}
    (args.capture / "lifetime_evidence.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"generations": generations, "transitions": transitions, "visual_matches": len(matches)}, indent=2))


if __name__ == "__main__":
    main()
