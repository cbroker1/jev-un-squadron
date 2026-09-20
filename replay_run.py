"""Play a recorded run back on screen, by its run number.

    python replay_run.py 116            # watch run 116
    python replay_run.py 116 --speed 50 # at half speed
    python replay_run.py --best-boss    # the longest boss attempt on record

The run's inputs.csv holds the masks Lua actually sent, so the playback is the run itself
rather than a re-decision: no Jev requests, no cost, and the same frames every time.
Slot 1 is loaded read-only and never written.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOSS_ENTRY_FRAME = 24121


def runs():
    for folder in sorted((ROOT / "runs").glob("combat-*live")):
        manifest, summary = folder / "manifest.json", folder / "summary.json"
        if not manifest.exists() or not (folder / "inputs.csv").exists():
            continue
        try:
            label = json.loads(manifest.read_text()).get("run_label")
            report = json.loads(summary.read_text()) if summary.exists() else {}
        except ValueError:
            continue
        if label:
            yield label, folder, report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", nargs="?", type=int, help="run number to play back")
    ap.add_argument("--best-boss", action="store_true", help="the longest boss attempt recorded")
    ap.add_argument("--speed", type=int, default=100, help="percent; 50 is half speed")
    ap.add_argument("--list", action="store_true", help="show what can be played back")
    args = ap.parse_args()
    available = list(runs())
    if args.list:
        for label, folder, report in available[-15:]:
            print(f"R{label}: to frame {report.get('final_frame')} ({report.get('reason')})")
        return
    if args.best_boss:
        boss = [(label, folder, report) for label, folder, report in available
                if (report.get("first_request_frame") or 0) >= 24000]
        if not boss:
            raise SystemExit("no boss attempts recorded yet")
        label, folder, report = max(boss, key=lambda item: item[2].get("final_frame") or 0)
        print(f"playing the longest boss attempt: R{label}, "
              f"{(report.get('final_frame') or 0)-BOSS_ENTRY_FRAME} frames in the fight")
    else:
        if not args.label:
            raise SystemExit("give a run number, or --best-boss, or --list")
        match = [item for item in available if item[0] == args.label]
        if not match:
            raise SystemExit(f"no run {args.label} with inputs on disk")
        label, folder, report = match[0]
    if '"EmuHawk.exe"' in subprocess.run(["tasklist", "/FI", "IMAGENAME eq EmuHawk.exe", "/FO", "CSV", "/NH"],
                                         capture_output=True, text=True).stdout:
        raise SystemExit("an emulator is already open; close it first")
    config = json.loads((ROOT / "config.json").read_text())
    slot = "3" if (report.get("first_request_frame") or 0) >= 24000 else "1"
    environment = dict(os.environ, JEV_REPLAY_INPUTS=str(folder / "inputs.csv"),
                       JEV_REPLAY_LABEL=str(label), JEV_REPLAY_SPEED=str(args.speed))
    note = ROOT / "replay_note.txt"
    note.unlink(missing_ok=True)
    emulator = subprocess.Popen([str(ROOT / "bizhawk/EmuHawk.exe"), "--load-slot", slot,
                                 "--lua", str(ROOT / "lua/replay_run.lua"), config["rom_path"]],
                                cwd=str(ROOT / "bizhawk"), env=environment)
    print(f"R{label} is playing back from slot {slot}; it closes itself at the end.")
    try:
        emulator.wait(timeout=900)
    except KeyboardInterrupt:
        emulator.terminate()
    except subprocess.TimeoutExpired:
        emulator.kill()
    if note.exists():
        print(note.read_text().strip())


if __name__ == "__main__":
    main()
