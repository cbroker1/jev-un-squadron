"""Rank possible screen-coordinate byte pairs from a hazard snapshot run.
Results are candidates only; this tool never feeds them to the controller.
"""
import argparse, csv, pathlib, statistics

SIZE = 0x20000

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=pathlib.Path)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    raw = (args.run / "wram_u8.bin").read_bytes()
    count = len(raw) // SIZE
    frames = list(csv.DictReader((args.run / "frames.csv").open(newline="")))
    rows = []
    for x in range(0, SIZE - 1):
        xs = [raw[i * SIZE + x] for i in range(count)]
        ys = [raw[i * SIZE + x + 1] for i in range(count)]
        if max(xs) - min(xs) < 4 or max(ys) - min(ys) < 4:
            continue
        # Reject pairs dominated by off-screen/sentinel values.
        if sum(v in (0, 255) for v in xs) > count * 0.45:
            continue
        if sum(v in (0, 255) or v > 223 for v in ys) > count * 0.45:
            continue
        valid = [i for i, (vx, vy) in enumerate(zip(xs, ys)) if 0 < vx < 256 and 0 < vy <= 223]
        if len(valid) < count * 0.35:
            continue
        changes = sum(xs[i] != xs[i - 1] or ys[i] != ys[i - 1] for i in range(1, count))
        score = statistics.pvariance(xs) + statistics.pvariance(ys)
        rows.append((score, x, x + 1, xs, ys, len(valid) / count, changes))
    rows.sort(reverse=True)
    out = args.run / "coordinate_candidates.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["status", "x_address", "y_address", "score", "samples", "valid_fraction", "motion_changes", "x_range", "y_range"])
        for score, x, y, xs, ys, valid_fraction, changes in rows[:args.top]:
            w.writerow(["UNVERIFIED", f"0x{x:04X}", f"0x{y:04X}", round(score, 2), len(xs), round(valid_fraction, 3), changes, f"{min(xs)}..{max(xs)}", f"{min(ys)}..{max(ys)}"])
    dynamic = args.run / "dynamic_candidates.csv"
    with dynamic.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["status", "x_address", "y_address", "valid_fraction", "motion_changes", "x_range", "y_range"])
        for score, x, y, xs, ys, valid_fraction, changes in sorted(rows, key=lambda row: row[6], reverse=True)[:args.top]:
            w.writerow(["UNVERIFIED", f"0x{x:04X}", f"0x{y:04X}", round(valid_fraction, 3), changes, f"{min(xs)}..{max(xs)}", f"{min(ys)}..{max(ys)}"])
    print(f"snapshots={count} frames={frames[0]['emu_frame']}..{frames[-1]['emu_frame']} candidates={len(rows)}")
    print(f"wrote {out}")
    print(f"wrote {dynamic}")
    for score, x, y, _, _, valid_fraction, changes in rows[:args.top]:
        print(f"UNVERIFIED X=0x{x:04X} Y=0x{y:04X} score={score:.2f} valid={valid_fraction:.2f} motion_changes={changes}")

if __name__ == "__main__":
    main()
