import json, pathlib

root = pathlib.Path(__file__).resolve().parents[1]
runs = []
for path in (root / "runs").glob("run-*.jsonl"):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if rows and rows[0].get("mode") == "calibrate": runs.append((path, rows))
if not runs:
    raise SystemExit("No calibration run found. Run: python bridge.py --calibrate")
path, rows = sorted(runs, key=lambda x: x[0].stat().st_mtime)[-1]
by_action = {r["requested_action"]: r["observed_state"] for r in rows}
base = by_action.get("hold", {})
neutral = base.get("candidate_values", {})
print(f"run={path.name}")
print("address,neutral,up,down,left,right,vertical_delta,horizontal_delta")
for address, n in neutral.items():
    vals = {k: by_action.get(k, {}).get("candidate_values", {}).get(address) for k in ("up", "down", "left", "right")}
    if any(v is None for v in vals.values()): continue
    # Signed deltas are evidence only; wraparound is reported plainly.
    y = ((vals["up"] - n) + (n - vals["down"])) / 2
    x = ((vals["right"] - n) + (n - vals["left"])) / 2
    print(f"{address},{n},{vals['up']},{vals['down']},{vals['left']},{vals['right']},{y:.1f},{x:.1f}")
