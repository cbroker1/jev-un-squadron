"""Run one owned, bounded combat experiment. Never close a user's emulator."""
import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import bridge
from brain.observations import SLOT1_SHA256
from probe_hazards import close_owned_window, save_json, sha256

ROOT=Path(__file__).resolve().parent
ACTIVE=ROOT / "runs/active_segment.json"


def validate(run, limit):
    report=json.loads((run / "summary.json").read_text())
    events=[json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    rows=list(csv.DictReader((run / "inputs.csv").open(newline="")))
    manifest=json.loads((run / "manifest.json").read_text())
    by_result={int(r["result_frame"]):r for r in rows}
    actions=[]
    for event in events:
        if event["event"] != "command": continue
        cmd=event["command"]
        actual=[r for r in rows if r["run_id"]==run.name and int(r["call"])==cmd["call"] and r["action"]!="stop"]
        if not actual:
            actions.append({"command_id":cmd["call"],"source":cmd["decision_source"],"applied_frames":0}); continue
        before=by_result.get(int(actual[0]["source_frame"]), actual[0])
        actions.append({"command_id":cmd["call"],"attempt":cmd["attempt"],"source":cmd["decision_source"],
            "action":cmd["action"],"requested_fire":cmd["fire"],"applied_frames":len(actual),
            "core_polled_frames":sum(int(r["input_polls"])>0 for r in actual),
            "first_apply_frame":int(actual[0]["source_frame"]),"last_result_frame":int(actual[-1]["result_frame"]),
            "start_xy":[int(before["player_x"]),int(before["player_y"])],
            "end_xy":[int(actual[-1]["player_x"]),int(actual[-1]["player_y"])]})
    selected=[a for a in actions if a["source"] in ("jev","deterministic_mock")]
    http_events=[e for e in events if e["event"]=="request"]
    final=json.loads((run / "final_state.json").read_text())
    expected_stop=manifest.get("expected_stop")
    expected=report["reason"]==expected_stop if expected_stop else report["reason"] in ("decision_budget","game_frame_budget")
    polled=[r for r in rows if int(r["input_polls"])>0]
    # During some scene transitions the core does not poll the controller.
    # That is unavailable readback, not a mismatched button or proof of effect.
    checks={"expected_completion":expected,
            "requests_accounted":len(http_events)==report["jev_requests"] <= limit,
            "offline_has_no_api":report["mode"]=="live" or report["jev_requests"]==0,
            "input_readback":bool(polled) and all(r["requested_mask"]==r["poll_mask"] for r in polled)
                and all(a.get("core_polled_frames",0)>0 for a in actions),
            "speed_50":bool(rows) and all(r["speed_percent"]=="50" for r in rows),
            "no_long_control_lease":all(0 < a["applied_frames"] <= 30 for a in actions),
            "stop_ack":bool(final) and final.get("bridge_run_id")==run.name and final["requested_mask"]==0 and final["applied_action"]=="stop",
            "save_unchanged":manifest["state_unchanged"],"owned_emulator_closed":manifest["emulator_exit_code"]==0}
    if report["mode"]!="baseline" and not expected_stop:
        # A run that ends on its frame budget may legitimately make fewer decisions
        # (no checked tracks to judge); every decision it did make must still apply.
        expected_decisions=limit if report["reason"]=="decision_budget" else report["decisions"]
        checks["all_budgeted_decisions_applied"]=len(selected)==expected_decisions and all(a["applied_frames"]>0 for a in selected)
    if expected_stop=="stale_reply_rejected":
        checks["stale_choice_never_injected"]=not selected
    jev_movement=any(a["source"]=="jev" and a.get("action")!="hold" and a.get("start_xy")!=a.get("end_xy") for a in selected)
    result={"pass":all(checks.values()),"checks":checks,"actions":actions,"jev_movement_observed_in_ram":jev_movement,
            "core_polled_frames":len(polled),"frames_without_core_poll":len(rows)-len(polled),
            "health_damage_death":None,"level_clear":None,"jev_requests":report["jev_requests"]}
    save_json(run / "validation.json",result)
    print(json.dumps({"run_id":run.name,"pass":result["pass"],"checks":checks,"jev_movement_observed_in_ram":jev_movement,"jev_requests":report["jev_requests"]}),flush=True)
    return result["pass"]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode",choices=("dry","live","baseline"),default="dry")
    ap.add_argument("--max-calls",type=int,default=5)
    ap.add_argument("--mock-delay-ms",type=int,default=250)
    ap.add_argument("--expect-stop",choices=("stale_reply_rejected",))
    ap.add_argument("--interval",type=int,default=30,help="game frames between decisions")
    ap.add_argument("--warmup",type=int,default=480,help="prelude game frames before decisions")
    ap.add_argument("--frames",type=int,default=210,help="maximum combat game frames after the prelude")
    ap.add_argument("--stepped",action="store_true",help="pause the emulator on each decision frame (pause-and-step)")
    ap.add_argument("--prelude-fire",action="store_true",help="Y firing during the prelude instead of gun off")
    ap.add_argument("--stop",action="store_true")
    args=ap.parse_args()
    if args.stop:
        active=json.loads(ACTIVE.read_text()) if ACTIVE.exists() else {}
        if active.get("running"):
            target=Path(active["run_dir"]).resolve()
            if not target.is_relative_to(ROOT / "runs") or target==ROOT / "runs":
                raise SystemExit("Invalid runner location")
            (target / "STOP").touch()
        print("Stop requested for this runner only."); return
    if not 1 <= args.max_calls <= 400:
        ap.error("Request limit must be 1..400")
    if not 1 <= args.interval <= 30:
        ap.error("Decision interval must be 1..30 game frames")
    if not (1 if args.stepped else 0) <= args.warmup <= 900 or not 1 <= args.frames <= 1800:
        ap.error("Warmup must be 0..900 (1.. when stepped) and frames 1..1800")
    if args.expect_stop and args.mode!="dry":
        ap.error("Expected-error tests are offline only")
    listing=subprocess.run(["tasklist","/FI","IMAGENAME eq EmuHawk.exe","/FO","CSV","/NH"],capture_output=True,text=True,check=True)
    if '"EmuHawk.exe"' in listing.stdout or (ROOT / "STOP").exists():
        raise SystemExit("An emulator or project STOP exists; preserving it, no run started.")
    save_now=ROOT / "bizhawk/SNES/State/U.N. Squadron (USA).Snes9x.QuickSave1.State"
    if sha256(save_now) != SLOT1_SHA256:
        raise SystemExit("Slot 1 does not match the evidence baseline (a save state was overwritten); no run started. "
                         "BizHawk keeps the previous state in the matching .bak file.")
    if args.mode=="live" and not (ROOT / "typesafe_api_key.txt").is_file():
        raise SystemExit("The existing local key file is missing; emulator not started.")
    run=ROOT / "runs" / ("combat-"+dt.datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6]+"-"+args.mode)
    run.mkdir()
    cfg=json.loads((ROOT / "config.json").read_text())
    exe=ROOT / "bizhawk/EmuHawk.exe"
    save=ROOT / "bizhawk/SNES/State/U.N. Squadron (USA).Snes9x.QuickSave1.State"
    manifest={"run_id":run.name,"mode":args.mode,"local_started":dt.datetime.now().astimezone().isoformat(),
        "rom_sha256":sha256(Path(cfg["rom_path"])),"slot1_sha256":sha256(save),"max_jev_attempts":args.max_calls if args.mode=="live" else 0,
        "expected_stop":args.expect_stop,"requested_speed":50,"core":"Snes9x","warmup_frames":args.warmup,
        "frame_budget":args.frames,"decision_timing":"pause_and_step" if args.stepped else "continuous",
        "prelude":"Y firing, no movement" if args.prelude_fire else "neutral, gun off","decision_interval_frames":args.interval,
        "lua_sha256":sha256(ROOT / "lua/main.lua"),"controller_sha256":sha256(ROOT / "play_segment.py")}
    save_json(run / "manifest.json",manifest)
    env=os.environ.copy(); env.pop("TYPESAFE_API_KEY",None)
    env.update(JEV_BRIDGE_TRACE=str(run),JEV_BRAIN_PREVIEW="1")
    emu=worker=None
    started=time.monotonic()
    print(f"{run.name}: {args.mode.upper()}, maximum Jev attempts {manifest['max_jev_attempts']}. Ctrl+C or stop_segment.bat stops.",flush=True)
    try:
        with (run / "emulator_stdout.txt").open("w") as out,(run / "emulator_stderr.txt").open("w") as err,(run / "console.txt").open("w") as console:
            emu=subprocess.Popen([str(exe),"--load-slot","1","--lua",str(ROOT / "lua/main.lua"),cfg["rom_path"]],cwd=exe.parent,env=env,stdout=out,stderr=err)
            save_json(ACTIVE,{"running":True,"run_dir":str(run),"pid":emu.pid})
            worker=subprocess.Popen([sys.executable,"-u",str(ROOT / "play_segment.py"),"--output",str(run),"--mode",args.mode,
                "--max-calls",str(args.max_calls),"--mock-delay-ms",str(args.mock_delay_ms),
                "--warmup",str(args.warmup),"--frames",str(args.frames),"--interval",str(args.interval)]
                +(["--stepped"] if args.stepped else [])+(["--prelude-fire"] if args.prelude_fire else []),cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            # Forward only controller output (which deliberately contains no secrets).
            import threading
            def forward():
                for line in worker.stdout:
                    console.write(line); console.flush(); print(line,end="",flush=True)
            stream=threading.Thread(target=forward,daemon=True); stream.start()
            try:
                # The worker enforces its own wall cap; this outer bound only adds margin.
                worker.wait(timeout=max(60,60+(args.warmup+args.frames)/15+(1.5*args.frames/args.interval if args.stepped else 0)))
            except (KeyboardInterrupt,subprocess.TimeoutExpired):
                (run / "STOP").touch()
                try: worker.wait(timeout=5)
                except subprocess.TimeoutExpired: worker.terminate(); worker.wait(timeout=5)
            stream.join(timeout=2)
        deadline=time.monotonic()+3
        final=None
        while time.monotonic()<deadline:
            state=bridge.read_state()
            if state and state.get("bridge_run_id")==run.name and state["applied_action"]=="stop" and state["requested_mask"]==0:
                final=state; break
            time.sleep(0.02)
        save_json(run / "final_state.json",final)
    finally:
        (run / "STOP").touch()
        bridge.release_controls(run.name)
        if worker and worker.poll() is None:
            try: worker.wait(timeout=5)
            except subprocess.TimeoutExpired: worker.terminate(); worker.wait(timeout=5)
        if emu and emu.poll() is None:
            close_owned_window(emu.pid)
            try: emu.wait(timeout=5)
            except subprocess.TimeoutExpired: emu.terminate(); emu.wait(timeout=5)
        manifest.update(worker_exit_code=worker.returncode if worker else None,emulator_exit_code=emu.returncode if emu else None,
            wall_seconds=round(time.monotonic()-started,3),state_unchanged=sha256(save)==manifest["slot1_sha256"])
        save_json(run / "manifest.json",manifest)
        save_json(ACTIVE,{"running":False,"run_dir":str(run)})
    if not (run / "summary.json").exists() or not validate(run,args.max_calls):
        raise SystemExit("Experiment did not pass; its own evidence is preserved in "+str(run))


if __name__=="__main__":
    main()
