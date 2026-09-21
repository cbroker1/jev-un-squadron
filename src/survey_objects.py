"""Survey the WRAM object table of a full-RAM capture, grouped by routine address.

Discovery only. Evidence so far: object records are 0x40 bytes from 0x1000
(player at 0x1000), byte 0 holds flags and bytes 1..3 a 24-bit little-endian
routine address; X/Y are signed 16.8 at +0x10/+0x13. A routine address is a
candidate object type until it is checked against screenshots. Nothing here is
enabled for the controller.
"""
import argparse
import csv
import json
from pathlib import Path

from brain.observations import captures, fixed24

TABLE = range(0x1000, 0x2000, 0x40)


def routine(record):
    """Bank:address text for bytes 1..3, e.g. C8 4A B0 02 -> $02:B04A."""
    return f"${record[3]:02X}:{record[2]:02X}{record[1]:02X}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--from-sample", type=int, default=0)
    args = ap.parse_args()
    types, points = {}, []
    for row, raw in captures(args.capture):
        sample = int(row["sample"])
        if sample < args.from_sample:
            continue
        for base in TABLE:
            record = bytes(raw[base:base+0x16])
            if record[0] == 0 or record[3] > 0x3F or record[1:4] == b"\0\0\0":
                continue
            name = routine(record)
            x, y = fixed24(record, 16), fixed24(record, 19)
            on_screen = 0 <= x < 256 and 0 <= y < 224
            entry = types.setdefault(name, {"samples": 0, "on_screen": 0, "slots": set(), "flags": set(),
                                            "byte8": set(), "first_sample": sample, "last_sample": sample,
                                            "x_range": None, "y_range": None})
            entry["samples"] += 1
            entry["slots"].add(base); entry["flags"].add(record[0]); entry["byte8"].add(record[8])
            entry["last_sample"] = sample
            if on_screen:
                entry["on_screen"] += 1
                for key, value in (("x_range", x), ("y_range", y)):
                    low, high = entry[key] or (value, value)
                    entry[key] = (min(low, value), max(high, value))
            points.append({"sample": sample, "emu_frame": int(row["emu_frame"]), "slot": f"0x{base:04X}",
                           "routine": name, "flags": f"{record[0]:02X}", "x": round(x, 3), "y": round(y, 3),
                           "on_screen": on_screen, "screenshot": row["screenshot"]})
    summary = {name: {**entry, "slots": [f"0x{s:04X}" for s in sorted(entry["slots"])],
                      "flags": [f"{f:02X}" for f in sorted(entry["flags"])], "byte8": sorted(entry["byte8"])}
               for name, entry in sorted(types.items(), key=lambda kv: -kv[1]["samples"])}
    (args.capture / "object_survey.json").write_text(json.dumps({
        "status": "discovery; routine addresses are candidate types until visually checked",
        "table": "0x1000..0x1FC0 step 0x40", "types": summary}, indent=2) + "\n")
    with (args.capture / "object_points.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(points[0]))
        writer.writeheader(); writer.writerows(points)
    for name, entry in summary.items():
        print(f"{name} samples={entry['samples']:4} on={entry['on_screen']:4} {entry['first_sample']}-{entry['last_sample']} "
              f"flags={','.join(entry['flags'])} +8={entry['byte8'][:3]} slots={' '.join(entry['slots'])[:70]} "
              f"x={entry['x_range'] and [round(v) for v in entry['x_range']]} y={entry['y_range'] and [round(v) for v in entry['y_range']]}")


if __name__ == "__main__":
    main()
