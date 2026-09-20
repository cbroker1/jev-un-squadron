"""File-based BizHawk bridge. Dry-run is deterministic and makes no network calls."""
import argparse, json, pathlib, time, os, urllib.request, uuid

ROOT = pathlib.Path(__file__).resolve().parent
RUNS = ROOT / "runs"
RUNS.mkdir(exist_ok=True)
STATE = ROOT / "runtime_state.json"
ACTION = ROOT / "runtime_action.json"
LOG = ROOT / "run.log"

def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    for _ in range(20):
        try:
            tmp.replace(path); return
        except PermissionError:
            time.sleep(0.025)
    # Never fall back to a partially readable action file. Lua expires old input.
    raise PermissionError("Could not atomically replace the bridge action file")

def read_state():
    """A concurrent Lua write is not an observation of frame zero."""
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if type(state.get("frame")) is not int or state["frame"] < 0:
            return None
        return state
    except (OSError, ValueError, AttributeError):
        return None

def wait_for_fresh_state(run_id, timeout=12):
    """Require this run's STOP acknowledgement and advancing frames before play."""
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        if (ROOT / "STOP").exists():
            raise InterruptedError("Project STOP requested")
        state = read_state()
        if (state and state.get("bridge_run_id") == run_id and state.get("lua_session_id")
                and isinstance(state.get("reload_epoch"), int)):
            if (previous and state.get("lua_session_id") == previous.get("lua_session_id")
                    and state.get("reload_epoch") == previous.get("reload_epoch")
                    and state["frame"] > previous["frame"]):
                return state
            previous = state
        time.sleep(0.02)
    raise TimeoutError("No fresh Lua acknowledgement. main.lua must be current, active and unpaused.")

def release_controls(run_id, calls=None):
    if calls is None:
        try:
            previous = json.loads(ACTION.read_text())
            calls = previous.get("call", 0) if previous.get("run_id") == run_id else 0
        except (OSError, ValueError):
            calls = 0
    write_json(ACTION, {"action": "stop", "fire": False, "fire_button": "Y",
                       "run_id": run_id, "expires_at_frame": 0, "call": calls})

def log_ack(run_log, run_id, result, state, acknowledged_call):
    if (result and state and state.get("last_applied_call") == result["call"]
            and state.get("last_applied_run_id") == run_id and acknowledged_call != result["call"]):
        ack = {"event": "input_ack", "run_id": run_id, "call": result["call"],
               "observe_to_apply_frames": state["first_apply_frame"] - result["observed_frame"],
               "issue_to_apply_frames": state["first_apply_frame"] - result["issued_at_frame"],
               "state_after_first_observed_application": state}
        with run_log.open("a", encoding="utf-8") as f: f.write(json.dumps(ack) + "\n")
        return result["call"]
    return acknowledged_call

def calibration_request(cfg, state):
    """Known axes are explicit; this remains a target test, not hazard avoidance."""
    return {"model": cfg.get("model", "jev-latest"),
            "state": {"experiment": "fixed_target_70_calibration_not_gameplay",
                      "frame": state["frame"], "player_y": state["player_y_candidate"],
                      "target_y": 70, "positive_y_direction": "down"},
            "questions": {"movement": {"type": "choice",
                "instructions": "Calibration only: choose a vertical direction toward target_y using player_y. Larger Y is lower on screen. Choose up when player_y > target_y, down when player_y < target_y, and hold only when equal. Firing is independently controlled by code.",
                "criteria": {"up": "Decrease Y toward the target", "down": "Increase Y toward the target", "hold": "Already at the target Y"}}}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--gun-test", action="store_true")
    ap.add_argument("--max-calls", type=int, default=None, help="bounded override for this run; config default remains 60")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    limit = max(1, int(args.max_calls if args.max_calls is not None else cfg.get("max_calls", 60)))
    interval = max(1, int(cfg.get("decision_interval_frames", 30)))
    if interval > 120:
        ap.error("decision_interval_frames must be at most 120 for bounded action leases")
    calls = 0
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_log = RUNS / ("run-" + run_id + ".jsonl")
    print("Bridge ready. Ctrl+C or the project STOP file stops safely.")
    LOG.write_text("", encoding="utf-8")
    mode = "gun-test" if args.gun_test else ("calibrate" if args.calibrate else ("live" if args.live else "dry-run"))
    print(f"run_id={run_id} mode={mode}")
    try:
        release_controls(run_id, 0)
        fresh = wait_for_fresh_state(run_id)
        with run_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "fresh_start", "run_id": run_id, "mode": mode,
                                "state": fresh, "jev_requests": 0}) + "\n")
        run(args, cfg, limit, interval, run_id, run_log, mode, fresh)
    except (KeyboardInterrupt, InterruptedError):
        print("Stop requested.")
    except (TimeoutError, PermissionError) as exc:
        print(str(exc))
    finally:
        try:
            release_controls(run_id)
            print("Stop command sent; Lua releases injected input on its next frame.")
        except PermissionError:
            print("Stop file write failed; Lua's bounded action expiry remains the fallback.")

def run(args, cfg, limit, interval, run_id, run_log, mode, fresh):
    calls = 0
    jev_requests = 0
    sequence = [("hold", 20), ("up", 20), ("down", 20), ("left", 20), ("right", 20), ("hold", 1)]
    sequence_index = 0
    sequence_frame = None
    last_frame_seen = fresh["frame"]
    previous_issued_frame = None
    last_result = None
    acknowledged_call = 0
    pending_since = None
    state_initialized = True
    no_progress_since = time.perf_counter()
    while calls < limit or ((args.calibrate or args.gun_test) and sequence_frame is not None):
        if (ROOT / "STOP").exists():
            return
        current = read_state()
        if current is None:
            if time.perf_counter() - no_progress_since > 3:
                raise TimeoutError("Lua state unavailable; stopping.")
            time.sleep(0.02)
            continue
        if (current.get("lua_session_id") != fresh.get("lua_session_id")
                or current.get("reload_epoch") != fresh.get("reload_epoch")):
            with run_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "lua_session_changed", "run_id": run_id,
                                    "state": current}) + "\n")
            print("Lua restarted or a save was loaded; stopping this run.")
            return
        current_frame_probe = int(current.get("frame", 0)) if current.get("frame") is not None else 0
        if state_initialized and (current.get("frame_regressed") is True or (last_frame_seen is not None and current_frame_probe < last_frame_seen)):
            event = {"run_id": run_id, "mode": mode, "event": "frame_regression", "previous_frame": last_frame_seen, "current_frame": current_frame_probe, "controls_released": True, "ts": time.time()}
            with run_log.open("a", encoding="utf-8") as f: f.write(json.dumps(event) + "\n")
            write_json(ACTION, {"action": "stop", "fire": False, "fire_button": "Y", "run_id": run_id, "expires_at_frame": 0, "call": calls})
            print(f"Emulated frame regression detected ({last_frame_seen}->{current_frame_probe}); controls released and run stopped.")
            return
        state_initialized = True
        if current_frame_probe != last_frame_seen:
            last_frame_seen = current_frame_probe
            no_progress_since = time.perf_counter()
        elif time.perf_counter() - no_progress_since > 3:
            write_json(ACTION, {"action": "stop", "fire": False, "run_id": run_id, "expires_at_frame": 0, "call": calls})
            print("No emulated-frame progress; controls released and run stopped.")
            return
        acknowledged_call = log_ack(run_log, run_id, last_result, current, acknowledged_call)
        if pending_since and acknowledged_call != calls and time.perf_counter() - pending_since > 3:
            raise TimeoutError("Lua did not acknowledge the action; stopping safely.")
        started = time.perf_counter()
        confidence = None
        probabilities = None
        override_reason = None
        if args.gun_test:
            buttons = ["A", "B", "X", "Y"]
            choice = "hold"
            fire_button = buttons[sequence_index] if sequence_index < len(buttons) else None
            new_probe = sequence_frame is None
            if new_probe: sequence_frame = -1
            if not new_probe and acknowledged_call == calls:
                sequence_frame = current["first_apply_frame"]
            if sequence_frame >= 0 and int(current.get("frame", 0)) - sequence_frame >= 120:
                sequence_index += 1; sequence_frame = None
                if sequence_index >= len(buttons): break
                continue
            if calls > 0 and not new_probe:
                time.sleep(0.02); continue
        elif args.calibrate:
            if sequence_index >= len(sequence):
                break
            choice, duration = sequence[sequence_index]
            new_probe = sequence_frame is None
            if new_probe:
                sequence_frame = -1
            if not new_probe and acknowledged_call == calls:
                sequence_frame = current["first_apply_frame"]
            current_frame = int(current.get("frame", 0))
            if sequence_frame >= 0 and current_frame - sequence_frame >= duration:
                with run_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"event": "probe_complete", "run_id": run_id, "call": calls,
                                        "requested_frames": duration, "first_apply_frame": sequence_frame,
                                        "observed_end_state": current}) + "\n")
                sequence_index += 1; sequence_frame = None; continue
            if calls > 0 and not new_probe:
                time.sleep(0.02)
                continue
        elif args.live:
            key = os.environ.get("TYPESAFE_API_KEY")
            if not key:
                print("Live mode requires a local TYPESAFE_API_KEY; stopping safely.")
                write_json(ACTION, {"action": "stop", "fire": False, "call": calls})
                return
            body = calibration_request(cfg, current)
            try:
                jev_requests += 1  # Count the attempt, including errors; there are no automatic retries.
                with run_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"event": "jev_request", "run_id": run_id,
                                        "attempt": jev_requests, "request_body": body}) + "\n")
                req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp: answer = json.loads(resp.read())
                decision = answer["answers"]["movement"]
                choice = decision["choice"]
                if choice not in ("up", "down", "hold"):
                    raise ValueError("Unexpected Choice option")
                if decision.get("confidence", 0) < 0.45:
                    override_reason = "legacy_calibration_confidence_below_0.45"
                confidence = decision.get("confidence")
                probabilities = decision.get("probabilities")
            except Exception as exc:
                # Keep the fail-safe behavior, but expose only a sanitized diagnostic.
                detail = type(exc).__name__
                if hasattr(exc, "code"): detail += f" HTTP {exc.code}"
                with run_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"event": "api_error", "run_id": run_id,
                                        "jev_requests": jev_requests, "detail": detail}) + "\n")
                print(f"Jev API error ({detail}); controls released and bridge stopped.")
                write_json(ACTION, {"action": "stop", "fire": False, "call": calls})
                return
        else:
            choice = ["up", "down", "hold"][calls % 3]
        latency = round((time.perf_counter() - started) * 1000, 1)
        calls += 1
        observed_frame = int(current.get("frame", 0)) if current.get("frame") is not None else 0
        issue_state = read_state()
        if (not issue_state or issue_state.get("lua_session_id") != fresh.get("lua_session_id")
                or issue_state.get("reload_epoch") != fresh.get("reload_epoch")
                or issue_state["frame"] < observed_frame):
            print("State changed or became unreadable during decision; rejecting action.")
            return
        issue_frame = issue_state["frame"]
        if args.live and issue_frame - observed_frame > interval:
            with run_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "stale_reply_rejected", "run_id": run_id,
                                    "requested_action": choice, "age_frames": issue_frame - observed_frame,
                                    "latency_ms": latency, "jev_requests": jev_requests}) + "\n")
            print("Jev reply exceeded the observation's frame-age budget; stopping, not applying it.")
            return
        fire = not args.calibrate
        default_fire_button = fire_button if args.gun_test else ("Y" if fire else None)
        action_window = 120 if args.gun_test else (duration if args.calibrate else interval)
        result = {"action": "hold" if override_reason else choice, "fire": fire, "fire_button": default_fire_button, "fire_pulse": bool(fire), "call": calls, "run_id": run_id, "observed_frame": observed_frame, "issued_at_frame": issue_frame, "interval_since_previous_issue_frames": None if previous_issued_frame is None else issue_frame - previous_issued_frame, "decision_interval_target_frames": interval, "expires_at_frame": issue_frame + action_window, "lua_session_id": fresh["lua_session_id"], "reload_epoch": fresh["reload_epoch"], "ts": time.time()}
        result["duration_frames"] = action_window
        result["expires_at_frame"] = issue_frame + max(3, action_window)
        last_result = result
        pending_since = time.perf_counter()
        previous_issued_frame = issue_frame
        write_json(ACTION, result)
        with LOG.open("a", encoding="utf-8") as f:
            record = {"run_id": run_id, "mode": mode, "observed_state": current, "requested_action": choice, "override_reason": override_reason, "confidence": confidence, "probabilities": probabilities, "latency_ms": latency, "observe_to_issue_frames": issue_frame - observed_frame, "resulting_action": result, "jev_requests": jev_requests, "policy": "fixed_target_70_calibration" if args.live else "deterministic_test"}
            f.write(json.dumps(record) + "\n")
        with run_log.open("a", encoding="utf-8") as f: f.write(json.dumps(record) + "\n")
        label = f"Jev request {calls}/{limit}" if args.live else f"test decision {calls}/{limit}; Jev requests: 0"
        print(f"{label}: {result['action']} + {'fire' if fire else 'no-fire'} ({mode})")
        if args.gun_test:
            time.sleep(0.02)
        elif args.calibrate:
            # The next loop waits until the current action's emulated-frame window expires.
            time.sleep(0.02)
        else:
            start_frame = observed_frame
            while True:
                time.sleep(0.02)
                if (ROOT / "STOP").exists(): return
                next_state = read_state()
                next_frame = next_state["frame"] if next_state else start_frame
                if next_state and (next_state.get("lua_session_id") != fresh.get("lua_session_id") or next_state.get("reload_epoch") != fresh.get("reload_epoch") or next_frame < start_frame):
                    with run_log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"event": "lua_session_changed", "run_id": run_id,
                                            "state": next_state}) + "\n")
                    print("Lua restarted or a save was loaded; stopping this run.")
                    return
                if next_frame != last_frame_seen:
                    last_frame_seen = next_frame
                    no_progress_since = time.perf_counter()
                if time.perf_counter() - no_progress_since > 3:
                    write_json(ACTION, {"action": "stop", "fire": False, "run_id": run_id, "expires_at_frame": 0, "call": calls})
                    print("No emulated-frame progress; controls released and run stopped.")
                    return
                if next_state is None:
                    continue  # Torn concurrent Lua write; the watchdog above still bounds persistent failures.
                acknowledged_call = log_ack(run_log, run_id, last_result, next_state, acknowledged_call)
                if acknowledged_call != calls:
                    if time.perf_counter() - pending_since > 3:
                        raise TimeoutError("Lua did not acknowledge the action; stopping safely.")
                    continue
                # Intermediate decisions use observation-to-observation spacing;
                # API latency consumes that interval, rather than adding a full sleep.
                # Only the final action gets its entire applied-frame lease before STOP.
                target = next_state["first_apply_frame"] + action_window if calls == limit else start_frame + interval
                if next_frame >= target: break
    write_json(ACTION, {"action": "stop", "fire": False, "run_id": run_id, "expires_at_frame": 0, "call": calls})
    print("Decision limit reached; controls released.")

if __name__ == "__main__":
    main()
