"""Gate/lifetime evidence for one aircraft-reference slot in a full-WRAM capture.

Evidence extraction only. The existing aircraft gate/reset code is applied to the
slot's bytes; running this does not enable a candidate for the controller.
Orange pixels are proximity evidence, not an object classifier.
"""
import argparse
import csv
import json
from pathlib import Path

from brain.observations import ENEMY_BASES, SlotTracker, captures


def s24(data, offset):
    return int.from_bytes(data[offset:offset+3], "little", signed=True)


def bbox_gap(component, x, y):
    dx = max(float(component["min_x"])-x, 0, x-float(component["max_x"]))
    dy = max(float(component["min_y"])-y, 0, y-float(component["max_y"]))
    return round((dx*dx+dy*dy)**0.5, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--base", type=lambda v: int(v, 0), default=0x1840)
    ap.add_argument("--compare", type=Path, help="second capture; report samples whose slot bytes are identical")
    args = ap.parse_args()
    base, name = args.base, args.capture.name
    orange = {}
    path = args.capture / "orange_components.csv"
    if path.exists():
        with path.open(newline="") as file:
            for component in csv.DictReader(file):
                orange.setdefault(int(component["sample"]), []).append(component)
    # Same gate and reset rules as the checked aircraft slots; only the label is this slot's.
    tracker = SlotTracker(base=ENEMY_BASES[0])
    rows, intervals, phantoms, marked = [], [], [], []
    integration = {axis: {"pairs": 0, "within_1_256_px": 0, "constant_velocity_pairs": 0, "constant_velocity_exact": 0,
                          "mismatches": []} for axis in "xy"}
    previous = None
    for row, raw in captures(args.capture):
        sample, frame = int(row["sample"]), int(row["emu_frame"])
        record = bytes(raw[base:base+0x1C])
        track = tracker.observe_slot(record[:22], frame, name)
        gated = track["phase"] == "observed_moving_signature"
        drawn = gated and track["on_screen"]
        state = (track["phase"], track["on_screen"], track["generation"])
        if not intervals or intervals[-1]["state"] != state:
            intervals.append({"state": state, "first_sample": sample, "first_xy": [track["x"], track["y"]]})
        intervals[-1].update(last_sample=sample, last_xy=[track["x"], track["y"]])
        if drawn and sample in orange:
            marked.append({"sample": sample, "xy": [track["x"], track["y"]],
                           "nearest_orange_bbox_gap_px": min(bbox_gap(c, track["x"], track["y"]) for c in orange[sample])})
        # The ungated u8 candidate that produced the earlier phantom markers.
        ux, uy = record[0x11], record[0x14]
        if not drawn and 8 <= ux < 248 and 40 <= uy < 190:
            phantoms.append({"sample": sample, "ungated_u8_xy": [ux, uy], "gated_xy": [track["x"], track["y"]],
                             "suppressed_by": "header gate" if not gated else "16.8 reference off-screen",
                             "nearest_orange_bbox_gap_px": min((bbox_gap(c, ux, uy) for c in orange.get(sample, [])), default=None)})
        rows.append({"sample": sample, "source_frame": frame, "header_hex": record[:14].hex(), "x": track["x"], "y": track["y"],
                     "phase": track["phase"], "on_screen": track["on_screen"], "generation": track["generation"],
                     "vx": track["vx"], "vy": track["vy"]})
        # Candidate velocity fields (+0x16, +0x19) checked against 16.8 motion; they are not adopted.
        if previous and frame-previous[0] == 2 and previous[1][0] == record[0] == 0xC8:
            for axis, position, velocity in (("x", 0x10, 0x16), ("y", 0x13, 0x19)):
                check = integration[axis]
                moved = s24(record, position)-s24(previous[1], position)
                v0, v1 = s24(previous[1], velocity), s24(record, velocity)
                check["pairs"] += 1
                if abs(moved-(v0+3*v1)/2) <= 1:
                    check["within_1_256_px"] += 1
                else:
                    check["mismatches"].append({"samples": [previous[2], sample], "moved_256ths": moved, "field_256ths": [v0, v1]})
                if v0 == v1:
                    check["constant_velocity_pairs"] += 1
                    check["constant_velocity_exact"] += moved == 2*v1
        previous = (frame, record, sample)
    for interval in intervals:
        phase, on_screen, generation = interval.pop("state")
        interval.update(phase=phase, on_screen=on_screen, generation=generation)
    comparison = None
    if args.compare:
        other = {int(r["sample"]): bytes(raw[base:base+0x40]) for r, raw in captures(args.compare)}
        common = [(int(r["sample"]), bytes(raw[base:base+0x40])) for r, raw in captures(args.capture) if int(r["sample"]) in other]
        comparison = {"other_capture": args.compare.name, "common_samples": len(common),
                      "identical_64_byte_records": sum(data == other[s] for s, data in common),
                      "active_identical_samples": [s for s, data in common if data == other[s] and data[0] == 0xC8]}
    report = {"source_capture": name, "base": f"0x{base:04X}", "jev_requests": 0,
              "status": "evidence only; slot reuse, type and colour are not decoded",
              "gate": "bytes +0..+3 == c8 4a b0 02 and +8 == 03 (existing aircraft research gate)",
              "coordinates": "signed 24-bit little-endian /256 at +0x10 (X) and +0x13 (Y)",
              "notes": ["Reference points, not hitboxes; part of a sprite can remain visible after the reference leaves the screen.",
                        "Velocity field candidates are reported only as support for the fractional coordinate bytes."],
              "intervals": intervals, "marked_orange_proximity": marked, "suppressed_ungated_u8_markers": phantoms,
              "velocity_field_integration": integration, "cross_capture": comparison, "samples": rows}
    out = args.capture / f"aircraft_slot_{base:04X}_evidence.json"
    out.write_text(json.dumps(report, indent=2)+"\n")
    gaps = [m["nearest_orange_bbox_gap_px"] for m in marked]
    print(json.dumps({"intervals": intervals, "marked_on_screen": len(gaps), "orange_within_3.1px": sum(g <= 3.1 for g in gaps),
                      "suppressed_ungated_u8": len(phantoms),
                      "integration": {a: {k: v for k, v in c.items() if k != "mismatches"} for a, c in integration.items()},
                      "cross_capture": comparison, "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
