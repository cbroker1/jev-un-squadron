"""Compare visual measurements with all WRAM bytes; never auto-promote candidates."""
import argparse
import csv
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--from-sample", type=int, default=568)
    ap.add_argument("--to-sample", type=int, default=622)
    ap.add_argument("--measurements", default="cyan_components.csv")
    ap.add_argument("--exact-pixels", type=int)
    args = ap.parse_args()
    with (args.run / args.measurements).open(newline="") as file:
        observations = [r for r in csv.DictReader(file) if int(r["pixels"]) >= 4
                        and (args.exact_pixels is None or int(r["pixels"]) == args.exact_pixels)
                        and args.from_sample <= int(r["sample"]) <= args.to_sample]
    samples = [r["sample"] for r in observations]
    if len(set(samples)) != len(samples) or len(samples) < 3:
        raise SystemExit("Need at least 3 images with one unambiguous component per sample.")
    raw = (args.run / "wram_u8.bin").read_bytes()
    snapshots = [raw[int(r["snapshot_index"])*0x20000:(int(r["snapshot_index"])+1)*0x20000]
                 for r in observations]
    if any(len(s) != 0x20000 for s in snapshots):
        raise SystemExit("Incomplete WRAM evidence")
    result = {"status": "candidate matches only", "visual_samples": samples, "axes": {}}
    for axis in ("x", "y"):
        targets = [float(r["center_" + axis]) for r in observations]
        if max(targets)-min(targets) < 3:
            result["axes"][axis] = {"status": "insufficient motion to identify this axis"}
            continue
        matches = []
        for address in range(0x20000):
            offsets = [(s[address]-target+128)%256-128 for s, target in zip(snapshots, targets)]
            if max(offsets)-min(offsets) <= 1 and abs(sum(offsets)/len(offsets)) <= 16:
                matches.append({"address": f"0x{address:04X}", "domain": "WRAM", "type": "u8",
                                "mean_pixel_offset": sum(offsets)/len(offsets),
                                "offset_spread": max(offsets)-min(offsets),
                                "values": [s[address] for s in snapshots]})
        result["axes"][axis] = {"match_count": len(matches), "matches": matches[:20]}
    (args.run / (Path(args.measurements).stem+"_ram_matches.json")).write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
