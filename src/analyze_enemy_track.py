"""Narrow the existing enemy-X candidate using independent colored sprite evidence.

The Y ranking is discovery only. It does not enable an object for controller use.
"""
import argparse
import csv
import json
from pathlib import Path
from brain.observations import captures, fixed24


def rank_orange(folder):
    """Test a +3 byte X/Y relationship as a hypothesis, not an accepted layout."""
    visual={}
    with (folder / "orange_components.csv").open(newline="") as file:
        for point in csv.DictReader(file):
            if (int(point["pixels"]) in (10,11) and int(point["max_y"])-int(point["min_y"])<=2
                    and int(point["max_x"])-int(point["min_x"])>=9):
                visual.setdefault(int(point["sample"]),[]).append(point)
    candidates={}
    for row,raw in captures(folder):
        points=visual.get(int(row["sample"]),[])
        if not points: continue
        data=bytes(raw)
        for address,x in enumerate(data[:-4]):
            if not 8<=x<248 or data[address+1]!=0: continue
            y=data[address+3]
            if not 40<=y<190 or data[address+4]!=0: continue
            near=[p for p in points if abs(float(p["center_x"])-x)<=10 and abs(float(p["center_y"])-y)<=6]
            if len(near)==1:
                p=near[0]
                candidates.setdefault(address,[]).append({"sample":int(row["sample"]),"source_frame":int(row["emu_frame"]),
                    "ram_xy":[x,y],"visual_xy":[float(p["center_x"]),float(p["center_y"])],"screenshot":row["screenshot"]})
    ranked=[]
    for address,points in candidates.items():
        if len(points)<8: continue
        spans=[max(p["ram_xy"][i] for p in points)-min(p["ram_xy"][i] for p in points) for i in (0,1)]
        if min(spans)<12: continue
        ranked.append({"x_address":f"0x{address:04X}","y_address":f"0x{address+3:04X}","matches":len(points),
                       "xy_span":spans,"points":points})
    ranked.sort(key=lambda entry:entry["matches"],reverse=True)
    (folder / "orange_candidates.json").write_text(json.dumps({"status":"UNVERIFIED discovery; colored fragments are not identities",
        "hypothesis":"u8 X/Y separated by three bytes; high bytes zero","candidates":ranked},indent=2)+"\n")
    print(json.dumps([{k:v for k,v in row.items() if k!="points"} for row in ranked[:20]],indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--discover-family", action="store_true")
    ap.add_argument("--orange", action="store_true")
    args = ap.parse_args()
    if args.orange:
        rank_orange(args.capture); return
    visual = {}
    with (args.capture / "green_components.csv").open(newline="") as file:
        for row in csv.DictReader(file):
            if int(row["pixels"]) in (14, 19):
                visual.setdefault(int(row["sample"]), []).append(row)
    if args.discover_family:
        found = {}
        for row, raw in captures(args.capture):
            data, cursor = bytes(raw), 0
            while True:
                base = data.find(bytes.fromhex("c84ab002"), cursor)
                if base < 0:
                    break
                cursor = base+4
                if base+22 > len(data) or data[base+8] != 3:
                    continue
                x,y = fixed24(data,base+16),fixed24(data,base+19)
                if not 8 <= x <= 247 or not 40 <= y <= 122:
                    continue
                near = [v for v in visual.get(int(row["sample"]),[]) if abs(float(v["center_x"])-x) <= 5 and abs(float(v["center_y"])-y) <= 3]
                if len(near) == 1:
                    found.setdefault(f"0x{base:04X}",[]).append({"sample": int(row["sample"]), "source_frame": int(row["emu_frame"]),
                        "ram_xy": [x,y], "visual_xy": [float(near[0]["center_x"]),float(near[0]["center_y"])], "screenshot": row["screenshot"]})
        (args.capture / "enemy_family_candidates.json").write_text(json.dumps({"status":"visual occurrence candidates; not complete enemy enumeration", "slots":found},indent=2)+"\n")
        print(json.dumps({base:len(points) for base,points in found.items()},indent=2))
        return
    points, snapshots = [], []
    for row, raw in captures(args.capture):
        sample = int(row["sample"])
        if not 550 <= sample <= 810:
            continue
        # Candidate neighborhood, NOT an assumed general enemy record layout.
        x = fixed24(raw, 0x16D0)
        if raw[0x16C0] != 0xC8 or not 8 <= x <= 247:
            continue
        nearby = [v for v in visual.get(sample, []) if abs(float(v["center_x"])-x) <= 5]
        if len(nearby) != 1:
            continue
        v = nearby[0]
        points.append({"sample": sample, "source_frame": int(row["emu_frame"]),
            "visual_x": float(v["center_x"]), "visual_y": float(v["center_y"]),
            "candidate_x": x, "screenshot": row["screenshot"]})
        snapshots.append(raw)
    if len(points) < 8 or max(p["visual_y"] for p in points)-min(p["visual_y"] for p in points) < 10:
        raise ValueError("Not enough independent positions to identify Y")
    matches = []
    for address in range(0x20000):
        errors = [abs(raw[address]-p["visual_y"]) for raw, p in zip(snapshots, points)]
        if max(errors) <= 3:
            matches.append({"address": f"0x{address:04X}", "mean_error": sum(errors)/len(errors), "max_error": max(errors)})
    matches.sort(key=lambda m: m["mean_error"])
    report = {"status": "candidate ranking, requires visual validation", "source_capture": args.capture.name,
              "jev_requests": 0, "points": points, "y_candidates": matches}
    (args.capture / "enemy_track_evidence.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"visual_points": len(points), "y_range": [min(p["visual_y"] for p in points), max(p["visual_y"] for p in points)],
                      "y_candidates": matches[:15]}, indent=2))


if __name__ == "__main__":
    main()
