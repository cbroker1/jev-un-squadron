"""Compare a short movement forecast with a separate controller-driven capture.

No API, emulator launch, key access, memory writes, or controller writes.
Pass means the tested reference-point trajectories match, NOT collision safety.
"""
import argparse
import csv
import json
import math
from pathlib import Path

from brain.observations import SlotTracker, captures, observation
from brain.digest import ACTIONS, player_position, summarize


def compare(reference, intervention):
    reference, intervention = Path(reference), Path(intervention)
    manifest = json.loads((intervention / "manifest.json").read_text())
    action = manifest["movement"].lower()
    if action not in ACTIONS or action == "hold" or manifest["mode"] != "neutral":
        raise ValueError("Expected a cardinal-only, no-fire intervention")
    start, end = manifest["move_from"] - 1, manifest["move_until"]
    horizon = end-start
    if not 1 <= horizon <= 30:
        raise ValueError("Intervention must be bounded to 1..30 frames")
    sources = {int(row["sample"]): (row, raw) for row, raw in captures(reference)}
    actual = {int(row["sample"]): (row, raw) for row, raw in captures(intervention)}
    if start not in sources or start not in actual or end not in actual:
        raise ValueError("Both the forecast source and intervention end must be captured")
    tracker = SlotTracker()
    source_obs = None
    for sample in sorted(sources):
        if sample > start:
            break
        row, raw = sources[sample]
        source_obs = observation(raw, row, reference.name, tracker)
    track = source_obs["tracks"][0]
    if track["vx"] is None or track["vy"] is None:
        raise ValueError("Source has no recent continuous projectile velocity")
    prediction = summarize(source_obs, horizon)
    common = sorted(set(sources) & set(actual))
    prefix = [sample for sample in common if sample <= start]
    prefix_identical = all(bytes(sources[s][1]) == bytes(actual[s][1]) for s in prefix)
    with (intervention / "inputs.csv").open(newline="") as file:
        inputs = list(csv.DictReader(file))
    mask = {"up": 1, "down": 2, "left": 4, "right": 8}[action]
    # Validate what reached the core, not just the CLI request in the manifest.
    polled = all(int(r["input_polls"]) > 0 and int(r["poll_mask"]) ==
                 (mask if start < int(r["sample"]) <= end else 0) for r in inputs)
    matches = []
    actual_tracker = SlotTracker()
    for sample in sorted(actual):
        row, raw = actual[sample]
        obs = observation(raw, row, intervention.name, actual_tracker)
        if not start <= sample <= end:
            continue
        delta = obs["source_frame"] - source_obs["source_frame"]
        expected_player = player_position(source_obs["player"]["x"], source_obs["player"]["y"], *ACTIONS[action], delta)
        expected_projectile = [track["x"]+track["vx"]*delta, track["y"]+track["vy"]*delta]
        measured_player = [obs["player"]["x"], obs["player"]["y"]]
        measured_track = obs["tracks"][0]
        measured_projectile = [measured_track["x"], measured_track["y"]]
        matches.append({"sample": sample, "source_frame": obs["source_frame"], "elapsed_game_frames": delta,
            "expected_player": expected_player, "observed_player": measured_player,
            "expected_projectile": expected_projectile, "observed_projectile": measured_projectile,
            "player_error_px": math.dist(expected_player, measured_player),
            "projectile_error_px": math.dist(expected_projectile, measured_projectile),
            "observed_anchor_gap_px": math.dist(measured_player, measured_projectile),
            "phase_matches": measured_track["phase"] == track["phase"],
            "screenshot": row["screenshot"]})
    final = matches[-1]
    checks = {"same_save_and_rom": True, "pre_intervention_ram_identical": prefix_identical,
        "actual_inputs_match_exact_window": polled, "at_least_three_positions": len(matches) >= 3,
        "frame_alignment": all(r["elapsed_game_frames"] == r["sample"]-start for r in matches),
        "player_within_half_pixel": max(r["player_error_px"] for r in matches) <= 0.5,
        "projectile_within_half_pixel": max(r["projectile_error_px"] for r in matches) <= 0.5,
        "projectile_phase_continuous": all(r["phase_matches"] for r in matches),
        "horizon_completed": final["elapsed_game_frames"] == horizon}
    # captures() already requires both runs' ROM/save hashes and runner checks.
    return {"reference_capture": reference.name, "intervention_capture": intervention.name,
        "action": action, "source_sample": start, "source_frame": source_obs["source_frame"],
        "horizon_frames": horizon, "decision_source": "deterministic_test", "jev_requests": 0,
        "forecast_uses_future_data": False, "checks": checks, "pass": all(checks.values()),
        "identical_prefix_snapshots": len(prefix) if prefix_identical else None,
        "projected_action": prediction["actions"][action], "observed_path": matches,
        "max_player_error_px": max(r["player_error_px"] for r in matches),
        "max_projectile_error_px": max(r["projectile_error_px"] for r in matches),
        "scope": "Reference-point trajectory validation only; no inferred damage, collision box, or survival score."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reference", type=Path)
    ap.add_argument("intervention", type=Path)
    args = ap.parse_args()
    report = compare(args.reference, args.intervention)
    output = args.intervention / "forecast_validation.json"
    output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pass", "checks", "max_player_error_px", "max_projectile_error_px", "jev_requests")}, indent=2))
    print(output)
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
