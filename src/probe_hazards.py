"""Own one bounded BizHawk experiment; never reads credentials or calls Jev."""
import argparse
import csv
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/hazard_observation"
ACTIVE = OUTPUT / "active_probe.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def request_stop():
    if not ACTIVE.exists():
        print("No experiment has been started by this runner.")
        return
    active = json.loads(ACTIVE.read_text())
    if not active.get("running"):
        print("The last experiment has already stopped.")
        return
    run = Path(active["run_dir"]).resolve()
    if not run.is_relative_to(OUTPUT.resolve()):
        raise ValueError("Invalid active experiment path")
    (run / "STOP").touch()
    print("Stop requested; the Lua experiment will release its inputs and close.")


def close_owned_window(pid):
    """WM_CLOSE only for windows of the process this runner created."""
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    ctypes.windll.user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    def visit(hwnd, _):
        owner = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True
    ctypes.windll.user32.EnumWindows(callback_type(visit), 0)


def replay_positions(run, source):
    """Every snapshot's player X/Y must equal the replayed run's logged X/Y at that frame."""
    with (source / "inputs.csv").open(newline="") as f:
        logged = {int(r["result_frame"]): (int(r["player_x"]), int(r["player_y"])) for r in csv.DictReader(f)}
    with (run / "frames.csv").open(newline="") as f:
        frames = [r for r in csv.DictReader(f) if int(r["emu_frame"]) in logged]
    return bool(frames) and all(logged[int(r["emu_frame"])] == (int(r["player_x"]), int(r["player_y"])) for r in frames)


def validate_run(run, expected_frames, replay_source=None):
    status = dict(line.split("=", 1) for line in (run / "status.txt").read_text().splitlines())
    with (run / "frames.csv").open(newline="") as f:
        frames = list(csv.DictReader(f))
    with (run / "inputs.csv").open(newline="") as f:
        inputs = list(csv.DictReader(f))
    binary_size = (run / "wram_u8.bin").stat().st_size
    polled = [r for r in inputs if int(r["input_polls"]) > 0]
    checks = {
        "lua_completed": status["status"] == "complete",
        "frame_budget": len(inputs) == expected_frames,
        "consecutive_frames": all(int(r["result_frame"]) == int(r["source_frame"])+1 for r in inputs),
        "speed_is_50": bool(inputs) and all(int(r["speed_percent"]) == 50 for r in inputs),
        "input_readback": bool(polled) and all(r["requested_mask"] == r["poll_mask"] for r in polled),
        "snapshot_length": binary_size == len(frames)*0x20000,
        "snapshot_indices": [int(r["snapshot_index"]) for r in frames] == list(range(len(frames))),
        "screenshots_exist": all((run / r["screenshot"]).is_file() for r in frames),
        "controls_released": status.get("controls_released") == "true",
    }
    if replay_source:
        checks["replay_positions_match"] = replay_positions(run, replay_source)
    summary = {"checks": checks, "pass": all(checks.values()), "input_frames": len(inputs),
               "polled_frames": len(polled), "snapshots": len(frames), "jev_requests": 0,
               "start_frame": status["start_frame"], "end_frame": status["end_frame"]}
    save_json(run / "validation.json", summary)
    print(json.dumps(summary), flush=True)
    return summary["pass"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", nargs="+", choices=["neutral", "held", "pulse6", "pulse8", "replay"], default=["neutral", "pulse6"])
    parser.add_argument("--replay-run", type=Path, help="runs/<run> whose inputs.csv requested masks are replayed (mode replay)")
    parser.add_argument("--frames", type=int, default=660)
    parser.add_argument("--capture-from", type=int, default=500)
    parser.add_argument("--capture-to", type=int, default=640)
    parser.add_argument("--fire-from", type=int, default=1)
    parser.add_argument("--fire-until", type=int, default=None)
    parser.add_argument("--move", choices=["neutral", "Up", "Down", "Left", "Right"], default="neutral")
    parser.add_argument("--move-from", type=int, default=1)
    parser.add_argument("--move-until", type=int, default=0)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.stop:
        request_stop(); return
    if not 1 <= args.frames <= 1800:
        parser.error("--frames must be between 1 and 1800")
    replay_source = args.replay_run.resolve() if args.replay_run else None
    if ("replay" in args.modes) != bool(replay_source) or (replay_source and not (replay_source / "inputs.csv").is_file()):
        parser.error("Mode replay needs --replay-run with an inputs.csv, and only then")
    # Never close somebody else's emulator, including a manually running game.
    running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    if running.returncode:
        raise SystemExit("Could not inspect running emulators; no probe started.")
    if '"EmuHawk.exe"' in running.stdout:
        raise SystemExit("BizHawk is already open; preserving that instance. No probe started.")
    if (ROOT / "STOP").exists():
        raise SystemExit("Project STOP file is present; no probe started.")
    config = json.loads((ROOT / "config.json").read_text())
    rom = Path(config["rom_path"])
    state = ROOT / "bizhawk/SNES/State/U.N. Squadron (USA).Snes9x.QuickSave1.State"
    exe = ROOT / "bizhawk/EmuHawk.exe"
    script = ROOT / "lua/hazard_snapshots.lua"
    run_group = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    OUTPUT.mkdir(exist_ok=True)
    for mode in args.modes:
        run = OUTPUT / ("probe_" + run_group + "_" + mode)
        run.mkdir()
        manifest = {"run_id": run.name, "local_started": dt.datetime.now().astimezone().isoformat(),
                    "mode": mode, "frames": args.frames, "capture_from": args.capture_from,
                    "capture_to": args.capture_to, "fire_from": args.fire_from,
                    "fire_until": args.fire_until if args.fire_until is not None else args.frames,
                    "movement": args.move, "move_from": args.move_from, "move_until": args.move_until,
                    "requested_speed_percent": 50,
                    "rom_sha256": sha256(rom), "state_sha256": sha256(state), "slot": 1,
                    "core_configured": "Snes9x", "script_sha256": sha256(script), "jev_requests": 0}
        if mode == "replay":
            # Replays requested masks only; the replay itself never calls Jev.
            with (replay_source / "inputs.csv").open(newline="") as f:
                masks = [(r["source_frame"], r["requested_mask"]) for r in csv.DictReader(f)]
            (run / "replay_masks.csv").write_text("".join(f"{a},{b}\n" for a, b in masks), encoding="utf-8")
            manifest.update(replay_run=replay_source.name, replay_inputs_sha256=sha256(replay_source / "inputs.csv"))
        save_json(run / "manifest.json", manifest)
        env = os.environ.copy()
        env.pop("TYPESAFE_API_KEY", None)
        env.update(HAZARD_OUTPUT=str(run), HAZARD_MODE=mode, HAZARD_FRAMES=str(args.frames),
                   HAZARD_CAPTURE_FROM=str(args.capture_from), HAZARD_CAPTURE_TO=str(args.capture_to),
                   HAZARD_FIRE_FROM=str(args.fire_from), HAZARD_FIRE_UNTIL=str(manifest["fire_until"]),
                   HAZARD_MOVE=args.move, HAZARD_MOVE_FROM=str(args.move_from), HAZARD_MOVE_UNTIL=str(args.move_until),
                   HAZARD_REPLAY=str(run / "replay_masks.csv") if mode == "replay" else "")
        print(f"{run.name}: {args.frames} game frames, 50% speed, 0 Jev calls. Esc or Ctrl+C stops.", flush=True)
        started = time.monotonic()
        with (run / "emulator_stdout.txt").open("w") as stdout, (run / "emulator_stderr.txt").open("w") as stderr:
            process = subprocess.Popen([str(exe), "--load-slot", "1", "--lua", str(script), str(rom)],
                                       cwd=exe.parent, env=env, stdout=stdout, stderr=stderr)
            save_json(ACTIVE, {"run_dir": str(run), "pid": process.pid, "running": True})
            interrupted = False
            try:
                while process.poll() is None:
                    if time.monotonic()-started > max(120, 60+args.frames/15):
                        raise TimeoutError("Experiment exceeded its wall-time budget")
                    # A Lua syntax error only reaches BizHawk's console; the script never starts.
                    if time.monotonic()-started > 30 and not (run / "emulator.txt").exists():
                        raise TimeoutError("Lua script did not start; check the BizHawk Lua console")
                    time.sleep(0.2)
            except (KeyboardInterrupt, TimeoutError) as exc:
                interrupted = True
                (run / "STOP").touch()
                print("Releasing experiment controls...", flush=True)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    close_owned_window(process.pid)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()  # Last resort: this process only, never other EmuHawks.
                        process.wait(timeout=5)
                manifest["interrupted"] = type(exc).__name__
            finally:
                manifest.update(wall_seconds=round(time.monotonic()-started, 3), exit_code=process.returncode,
                                state_unchanged=sha256(state) == manifest["state_sha256"])
                save_json(run / "manifest.json", manifest)
                save_json(ACTIVE, {"run_dir": str(run), "pid": process.pid, "running": False})
        if (run / "error.txt").exists():
            print("Lua error:\n" + (run / "error.txt").read_text(errors="replace"), flush=True)
        if interrupted or not (run / "status.txt").exists() or not validate_run(run, args.frames, replay_source if mode == "replay" else None):
            print(f"Probe stopped or failed; preserved evidence in {run}. No further runs started.")
            return
    print("Bounded experiment complete. BizHawk closed. Jev calls: 0.")


if __name__ == "__main__":
    main()
