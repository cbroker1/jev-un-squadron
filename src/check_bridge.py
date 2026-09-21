"""Bounded, zero-API check of the real bridge; shares the existing runner helpers."""
import argparse
import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

import bridge
from probe_hazards import close_owned_window, save_json, sha256

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["calibrate", "dry-run", "reload", "expiry", "brain-preview"], default="calibrate")
    args = parser.parse_args()
    listing = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, check=True)
    if '"EmuHawk.exe"' in listing.stdout or (ROOT / "STOP").exists():
        raise SystemExit("Existing emulator or STOP file present; no check started.")
    group = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run = ROOT / "runs" / ("bridge-check-" + group)
    run.mkdir()
    config = json.loads((ROOT / "config.json").read_text())
    exe = ROOT / "bizhawk/EmuHawk.exe"
    script = ROOT / ("lua/reload_main_test.lua" if args.mode == "reload" else "lua/main.lua")
    state_path = ROOT / "bizhawk/SNES/State/U.N. Squadron (USA).Snes9x.QuickSave1.State"
    manifest = {"run_id": run.name, "jev_requests": 0, "mode": args.mode, "requested_speed": 50,
                "rom_sha256": sha256(Path(config["rom_path"])), "slot1_sha256": sha256(state_path),
                "lua_sha256": sha256(script), "bridge_sha256": sha256(ROOT / "src/bridge.py")}
    env = os.environ.copy()
    env.pop("TYPESAFE_API_KEY", None)
    env["JEV_BRIDGE_TRACE"] = str(run)
    if args.mode == "brain-preview":
        env["JEV_BRAIN_PREVIEW"] = "1"
    print(f"{run.name}: {args.mode}, regular bridge, 50% speed, zero Jev requests.", flush=True)
    started = time.monotonic()
    process = worker = None
    try:
        with (run / "emulator_stdout.txt").open("w") as out, (run / "emulator_stderr.txt").open("w") as err:
            process = subprocess.Popen([str(exe), "--load-slot", "1", "--lua", str(script), config["rom_path"]],
                                       cwd=exe.parent, env=env, stdout=out, stderr=err)
            # Deliberately start immediately: the bridge must not consume the old state file.
            with (run / "bridge_console.txt").open("w") as output:
                if args.mode == "brain-preview":
                    command = [sys.executable, "-u", str(ROOT / "src/observe_brain.py"), "--output", str(run), "--frames", "900"]
                else:
                    command = [sys.executable, "-u", str(ROOT / "src/bridge.py")]
                    command += ["--calibrate"] if args.mode == "calibrate" else ["--dry-run", "--max-calls", "3"]
                worker = subprocess.Popen(command,
                                          cwd=ROOT, env=env, stdout=output, stderr=output)
                if args.mode == "expiry":
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        latest = bridge.read_state()
                        if latest and latest.get("applied_action") == "up" and latest.get("applied_call") == 1:
                            # Intentionally crash only our zero-API child to test Lua's lease.
                            worker.terminate()
                            manifest["intentional_bridge_crash"] = True
                            break
                        time.sleep(0.02)
                worker.wait(timeout=45 if args.mode == "brain-preview" else 30)
            manifest["bridge_exit_code"] = worker.returncode
            output_text = (run / "bridge_console.txt").read_text()
            match = re.search(r"run_id=([\w-]+)", output_text)
            expected_run = run.name if args.mode == "brain-preview" else (match.group(1) if match else None)
            deadline = time.monotonic() + 5
            final = None
            while time.monotonic() < deadline:
                latest = bridge.read_state()
                if (latest and expected_run and latest.get("bridge_run_id") == expected_run
                        and latest.get("applied_action") == "stop" and latest.get("input_poll_mask") == 0):
                    final = latest
                    break
                time.sleep(0.02)
            save_json(run / "final_state.json", final)
            if final and args.mode in ("reload", "expiry"):
                # Watch thirty further game frames for any replay of the old command.
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    latest = bridge.read_state()
                    if latest and latest["frame"] >= final["frame"] + 30:
                        save_json(run / "after_stop_state.json", latest)
                        break
                    time.sleep(0.02)
    finally:
        if worker is not None and worker.poll() is None:
            # Only this child; the emulator's frame/wall expiry remains active.
            worker.terminate()
            worker.wait(timeout=5)
        if process is not None and process.poll() is None:
            close_owned_window(process.pid)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                manifest["forced_own_emulator_exit"] = True
                process.terminate()
                process.wait(timeout=5)
        manifest.update(wall_seconds=round(time.monotonic()-started, 3),
                        emulator_exit_code=process.returncode if process else None,
                        state_unchanged=sha256(state_path) == manifest["slot1_sha256"])
        save_json(run / "manifest.json", manifest)
    rows = list(csv.DictReader((run / "inputs.csv").open(newline="")))
    active = [r for r in rows if r["action"] != "stop"]
    checks = {"bridge_exit_ok": manifest["bridge_exit_code"] == 0 or manifest.get("intentional_bridge_crash", False),
              "fresh_ack": bool(active), "cardinals_present": set(r["action"] for r in active) == {"hold", "up", "down", "left", "right"},
              "polled_input_matches": bool(active) and all(r["requested_mask"] == r["poll_mask"] and int(r["input_polls"]) > 0 for r in active),
              "speed_50": bool(rows) and all(r["speed_percent"] == "50" for r in rows),
              "stop_readback": final is not None, "state_unchanged": manifest["state_unchanged"],
              "emulator_closed_normally": manifest["emulator_exit_code"] == 0}
    actions = []
    for call in sorted(set(int(r["call"]) for r in active)):
        selected = [r for r in active if int(r["call"]) == call]
        actions.append({"call": call, "action": selected[0]["action"], "frames": len(selected),
                        "first_source_frame": int(selected[0]["source_frame"]),
                        "last_result_frame": int(selected[-1]["result_frame"]),
                        "first_xy": [int(selected[0]["player_x"]), int(selected[0]["player_y"])],
                        "last_xy": [int(selected[-1]["player_x"]), int(selected[-1]["player_y"])]})
    checks.pop("cardinals_present")
    expected = ["hold", "up", "down", "left", "right", "hold"] if args.mode == "calibrate" else ["up", "down", "hold"]
    if args.mode in ("calibrate", "dry-run"):
        checks["action_order"] = [a["action"] for a in actions] == expected
        checks["exact_frame_durations"] = [a["frames"] for a in actions] == ([20]*5 + [1] if args.mode == "calibrate" else [30]*3)
    if args.mode == "calibrate":
        checks["cardinal_end_positions"] = [a["last_xy"] for a in actions] == [[96,112], [96,62], [96,112], [46,112], [96,112], [96,112]]
    if args.mode == "brain-preview":
        from brain.observations import captures, PROJECTILE_BASES, fixed24
        if not (run / "brain_validation.json").exists():
            checks["brain_preview_completed"] = False
            save_json(run / "validation.json", {"pass": False, "checks": checks, "jev_requests": 0})
            print((run / "bridge_console.txt").read_text(), flush=True)
            raise SystemExit("Passive preview did not finish; this run's evidence was preserved.")
        report = json.loads((run / "brain_validation.json").read_text())
        records = [json.loads(line) for line in (run / "brain_stream.jsonl").read_text().splitlines()]
        checks["fresh_ack"] = report["observations"] > 850
        checks["polled_input_matches"] = bool(rows) and all(r["requested_mask"] == "0" and r["poll_mask"] == "0" for r in rows)
        checks["passive_no_commands"] = not active and report["movement_or_fire_commands"] == 0
        checks["zero_api_requests"] = report["jev_requests"] == 0
        checks["frame_budget"] = 900 <= report["end_frame"] - report["start_frame"] <= 901 and report["reason"] == "frame_budget"
        intervals = [r["interval_since_previous_preview_frames"] for r in records if r.get("interval_since_previous_preview_frames") is not None]
        checks["preview_spacing_in_game_frames"] = bool(intervals) and all(n == 30 for n in intervals)
        checks["continuous_tracks_observed"] = report["frames_with_velocity"] > 100
        # Compare this live file-bridge stream against independent full-WRAM captures.
        reference = ROOT / "evidence/hazard_observation/probe_20260919-114543-d95c1f_neutral"
        observed = {r["observed_state"]["source_frame"]: r["observed_state"] for r in records}
        matched, mismatches, image_matches, image_mismatches = 0, [], 0, []
        for row, raw in captures(reference):
            frame = int(row["emu_frame"])
            obs = observed.get(frame)
            if not obs:
                continue
            matched += 1
            if [obs["player"]["x"], obs["player"]["y"]] != [raw[0x1011],raw[0x1014]]:
                mismatches.append({"frame": frame, "field": "player"})
            for base, track in zip(PROJECTILE_BASES, obs["tracks"]):
                if [track["x"],track["y"]] != [fixed24(raw,base+16),fixed24(raw,base+19)]:
                    mismatches.append({"frame": frame, "field": f"slot 0x{base:04X}"})
            image = run / f"brain_frame_{frame}.png"
            if image.exists():
                if sha256(image) == sha256(reference / row["screenshot"]):
                    image_matches += 1
                else:
                    image_mismatches.append(frame)
        checks["reference_coordinate_matches"] = matched >= 190 and not mismatches
        checks["reference_image_matches"] = image_matches >= 15 and not image_mismatches
        save_json(run / "reference_comparison.json", {"reference_capture": reference.name,
            "shared_snapshots": matched, "coordinate_mismatches": mismatches,
            "identical_screenshots": image_matches, "screenshot_mismatch_frames": image_mismatches})
    if args.mode in ("reload", "expiry"):
        after = json.loads((run / "after_stop_state.json").read_text()) if (run / "after_stop_state.json").exists() else None
        checks["no_stale_replay_30_frames"] = bool(after) and after["input_poll_mask"] == 0 and after["applied_action"] == "stop"
        if args.mode == "reload":
            checks["actual_save_reload"] = bool(final) and final["reload_epoch"] > 0
            checks["post_reload_no_injected_input"] = all(r["requested_mask"] == "0" for r in rows if int(r["epoch"]) > 0)
        else:
            checks["lease_expired_at_30_frames"] = len(actions) == 1 and actions[0]["frames"] == 30
    save_json(run / "validation.json", {"pass": all(checks.values()), "checks": checks, "actions": actions, "jev_requests": 0})
    print((run / "bridge_console.txt").read_text(), flush=True)
    print(json.dumps({"run": run.name, "checks": checks, "actions": actions}), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
