"""Compare explicit run numbers, with comparable starts/budgets and known outcomes.

Offline only. Missing analyses are errors, never zero kills or zero damage.
Example: python compare_runs.py 124 125 --output runs/redesign_comparison.json
"""
import argparse
import json
from pathlib import Path
from statistics import median

from unit_census import census


def measure(run):
    manifest = json.loads((run / "manifest.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    outcomes = json.loads((run / "decision_trace.json").read_text())["candidate_table_events"]
    if not isinstance(outcomes, dict):
        raise ValueError(f"No outcome analysis for {run.name}")
    start = summary["first_request_frame"]
    if not start:
        raise ValueError(f"No decisions in {run.name}")
    met, _, killed = census(run, start)
    sizes, latencies, confidences = [], [], []
    objectives, selections = {}, {}
    for line in (run / "events.jsonl").open():
        event = json.loads(line)
        if event["event"] == "request":
            sizes.append(len(json.dumps(event["request_body"]).encode()))
        if event["event"] == "response":
            reply = event["response"]
            latencies.append(event["latency_ms"])
            if reply.get("confidence") is not None:
                confidences.append(reply["confidence"])
            for name, counts in (("objective", objectives), ("selection_reason", selections)):
                value = reply.get(name)
                if value:
                    counts[value] = counts.get(value, 0)+1
    return {"run":manifest["run_label"], "folder":str(run), "policy":manifest.get("policy", "legacy"),
            "change":manifest.get("change_under_test"), "first_request_frame":start,
            "frame_budget":manifest["frame_budget"], "interval":manifest["decision_interval_frames"],
            "prelude":manifest.get("prelude"), "timing":manifest.get("decision_timing"),
            "slot1_sha256":manifest.get("slot1_sha256"),
            "final_frame":summary["final_frame"], "observed_frames":summary["final_frame"]-start,
            "reason":summary["reason"], "units_met":sum(met.values()), "units_destroyed":sum(killed.values()),
            "share":sum(killed.values())/sum(met.values()) if sum(met.values()) else None,
            "hits":len(outcomes["hit_marker_frames"]),
            "hits_before_decisions":sum(frame < start for frame in outcomes["hit_marker_frames"]),
            "boss_parts_destroyed":len(outcomes["boss_parts_destroyed"]),
            "requests":summary["jev_requests"], "applied_jev":summary["applied_jev_decisions"],
            "applied_fallback":summary.get("applied_fallback_decisions", 0),
            "median_request_bytes":median(sizes) if sizes else None,
            "median_latency_ms":median(latencies) if latencies else None,
            "median_confidence":median(confidences) if confidences else None,
            "objectives":objectives, "selections":selections}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=int, nargs="+")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folders = {}
    for run in args.runs.glob("combat-*"):
        try:
            label = json.loads((run / "manifest.json").read_text()).get("run_label")
        except (OSError, ValueError):
            continue
        if label in args.labels:
            folders[label] = run
    missing = set(args.labels)-set(folders)
    if missing:
        parser.error(f"Missing run labels: {sorted(missing)}")
    rows = [measure(folders[label]) for label in args.labels]
    matching = ("first_request_frame", "frame_budget", "interval", "prelude", "timing", "slot1_sha256")
    mismatches = [field for field in matching if len({row[field] for row in rows}) > 1]
    print("Matched starts/budgets." if not mismatches else "NOT MATCHED: "+", ".join(mismatches))
    print(f"{'run':>4} {'policy':>15} {'units':>9} {'share':>6} {'hits':>5} {'frames':>7} {'fallback':>9} {'bytes':>7} {'ms':>7}")
    for row in rows:
        share = f"{row['share']:.0%}" if row['share'] is not None else "n/a"
        print(f"{row['run']:>4} {row['policy']:>15} {row['units_destroyed']:>4}/{row['units_met']:<4} "
              f"{share:>6} {row['hits']:>5} {row['observed_frames']:>7} {row['applied_fallback']:>9} "
              f"{row['median_request_bytes']:>7.0f} {row['median_latency_ms']:>7.0f}")
    if args.output:
        args.output.write_text(json.dumps({"matched":not mismatches,"mismatches":mismatches,"runs":rows}, indent=2)+"\n")


if __name__ == "__main__":
    main()
