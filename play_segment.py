"""Bounded experimental combat on the existing Lua bridge, not level completion.

One API request in flight. By default the main thread keeps observing game frames
while the request runs. With --stepped, Lua pauses the emulator on each decision
frame and the answer is applied to the very next emulated frame (pause-and-step).
Dry/baseline modes never read credentials and never call HTTP.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import time
import traceback
import urllib.request

import bridge
from brain.observations import TableTracker, bridge_observation
from brain.combat import combat_digest, combat_request
from brain.digest import ACTIONS

ROOT = Path(__file__).resolve().parent
SAVE_FRAME = 20183  # slot 1 resumes here; a later start means the emulator ran before Lua attached
# The player's own object slot switches to this routine when the aircraft is destroyed,
# seen at the end of two recordings. The aircraft then sits motionless while commands are
# still accepted: one run kept deciding for 64 frames after it died, and those decisions
# were paid for and counted. This ends the run instead; it is not a health or damage map,
# and nothing about it is shown to Jev.
DESTROYED_ROUTINE = bytes.fromhex("9be104")     # $04:E19B in slot 0x1000
DESTROYED_FRAMES_BEFORE_STOPPING = 3


def validate_answer(answer):
    result = answer["answers"]["movement"]
    if result["choice"] not in ACTIONS:
        raise ValueError("Choice outside the offered action set")
    confidence = result["confidence"]
    probabilities = result["probabilities"]
    if (type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0 <= confidence <= 1
            or set(probabilities) != set(ACTIONS)
            or any(type(p) not in (int,float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
            or abs(sum(probabilities.values())-1) > 0.01):
        raise ValueError("Invalid Choice distribution")
    # Whitelist response fields: never log raw HTTP bodies, headers or error text.
    return {"choice": result["choice"], "confidence": confidence, "probabilities": probabilities}


def decide(body, mode, attempt, key=None, delay_ms=250):
    started = time.perf_counter()
    if mode == "dry":
        time.sleep(delay_ms/1000)
        choice = ("up", "down", "up", "down", "hold")[(attempt-1) % 5]
        response = {"choice": choice, "confidence": None, "probabilities": None}
    elif mode == "live":
        request = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer "+key, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=3) as reply:
            response = validate_answer(json.loads(reply.read()))
    else:
        raise ValueError("Baseline must not request a decision")
    return response, round((time.perf_counter()-started)*1000, 2)


def reply_is_fresh(observed, current, max_age):
    return (current["lua_session_id"] == observed["lua_session_id"]
            and current["reload_epoch"] == observed["reload_epoch"]
            and 0 <= current["frame"]-observed["frame"] <= max_age)


def threat_gap(digest, action):
    """Smallest projected reference gap to a tracked bullet, aircraft or tank for one action."""
    option = digest["actions"][action]
    gaps = [g for g in (option["closest_anchor_distance_px"], option["enemy_body_anchor_gap_px"]) if g is not None]
    return min(gaps) if gaps else None


def wait_for_freeze(frame, timeout=1.0):
    """Lua's paused heartbeat at this exact frame, or None if the pause was not confirmed."""
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        state = bridge.read_state()
        if state and state["frame"] == frame and state.get("frozen") is True:
            return state
        if state and state["frame"] > frame:
            return None
        time.sleep(0.002)
    return None


def run(output, mode, limit=5, interval=30, warmup=480, frame_budget=210, max_age=20, delay_ms=250, key=None,
        expected_start=SAVE_FRAME,
        stepped=False, prelude_fire=False, recheck=6, replan_after=6):
    replan_after = min(replan_after, interval)
    run_id = output.name
    last_decision = None
    seen_tracks, entry_edges = set(), {}
    stepping = stepped and mode != "baseline"
    next_step = None
    heartbeat = None
    # Scales with the frame budget and paused decisions; still a hard safety cap.
    wall_limit = max(90, 30+(warmup+frame_budget)/15+(1.5*frame_budget/interval if stepping else 0))
    tracker = TableTracker()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bounded-jev-choice")
    pending = None
    requests = decisions = applied_jev = command_id = 0
    last_frame = last_preview_frame = None
    last_command = None
    acknowledged = set()
    first_request = None
    progress = wall_start = time.monotonic()
    reason = "unknown"
    final = None
    with (output / "events.jsonl").open("x", encoding="utf-8") as events, (output / "states.jsonl").open("x", encoding="utf-8") as states:
        def log(event, **fields):
            events.write(json.dumps({"event":event, "run_id":run_id, **fields})+"\n"); events.flush()
        def command(state, action, fire, source, attempt=None, observed=None, freeze_at=0):
            nonlocal command_id, last_command
            command_id += 1
            issued = state["frame"]
            value = {"run_id":run_id, "call":command_id, "action":action, "fire":fire,
                "fire_button":"Y", "fire_pulse":True, "duration_frames":interval,
                "observed_frame": observed["frame"] if observed else issued, "issued_at_frame":issued,
                "expires_at_frame":issued+3, "lua_session_id":state["lua_session_id"],
                "reload_epoch":state["reload_epoch"], "ts":time.time(), "freeze_at_frame":freeze_at}
            bridge.write_json(bridge.ACTION,value)
            last_command = dict(value, decision_source=source, attempt=attempt)
            log("command", command=last_command, requested_action=action, override_reason=None)
        try:
            bridge.release_controls(run_id,0)
            fresh = bridge.wait_for_fresh_state(run_id)
            # Anchor a launched comparison to the Lua/save origin, not variable
            # Python startup/handshake time. Reloads still end the entire run.
            start = fresh.get("experiment_start_frame",fresh["frame"])
            if start > expected_start+30:
                reason="emulator_started_late"
                log(reason, experiment_start_frame=start, expected_start_frame=expected_start)
                raise InterruptedError("Lua attached after the save frame; no request was made")
            decision_start, stop_frame = start+warmup, start+warmup+frame_budget
            log("start", mode=mode, state=fresh, experiment_start_frame=start,
                decision_start_frame=decision_start, stop_frame=stop_frame,
                warmup_frames=warmup, frame_budget=frame_budget,
                decision_interval_frames=interval, max_reply_age_frames=max_age, max_jev_attempts=limit if mode=="live" else 0,
                warmup_policy="Y firing, no movement" if prelude_fire else "neutral, gun off",
                decision_timing="pause_and_step" if stepping else "continuous", known_coverage="object table typed by routine: helicopters, bullets, power-ups, tanks; incomplete")
            print(f"{run_id}: {mode}; 50% speed; warmup {warmup} frames ({'firing' if prelude_fire else 'gun off'}); "
                  f"{'pause-and-step' if stepping else 'continuous'}; Jev limit {limit if mode=='live' else 0}. Ctrl+C stops.",flush=True)
            next_step = decision_start
            recent_positions = []
            recent_body_gaps = []
            destroyed = 0
            while True:
                if (ROOT / "STOP").exists() or (output / "STOP").exists():
                    reason="user_stop"; break
                state = bridge.read_state()
                if time.monotonic()-progress > 3 or time.monotonic()-wall_start > wall_limit:
                    raise TimeoutError("No state progress or wall-time budget exceeded")
                if state is None:
                    time.sleep(0.005); continue
                # An empty run id means Lua could not read the action file this frame, not a takeover.
                if ((state.get("bridge_run_id") or run_id) != run_id or state["lua_session_id"] != fresh["lua_session_id"]
                        or state["reload_epoch"] != fresh["reload_epoch"]
                        or (last_frame is not None and state["frame"] < last_frame)):
                    reason="reload_or_other_bridge"; break
                if state["frame"] == last_frame:
                    # A paused Lua heartbeat is progress; a silent frame is not.
                    if stepping and state.get("frozen") is True and state.get("freeze_heartbeat") != heartbeat:
                        heartbeat = state.get("freeze_heartbeat"); progress = time.monotonic()
                    time.sleep(0.005); continue
                last_frame = state["frame"]
                final = state
                progress = time.monotonic()
                table = (state.get("observation_profile") or {}).get("object_table")
                if table:
                    first_record = bytes.fromhex(table["bytes_hex"])[:22]
                    destroyed = destroyed+1 if bytes(first_record[1:4]) == DESTROYED_ROUTINE else 0
                    if destroyed >= DESTROYED_FRAMES_BEFORE_STOPPING:
                        reason="player_object_destroyed"
                        log(reason, frame=state["frame"], player_xy=[state["player_x_candidate"],
                                                                    state["player_y_candidate"]])
                        break
                obs = bridge_observation(state,tracker)
                obs.pop("live_control_ready",None)
                obs.update(mode="experimental_"+mode, complete_hazard_coverage=False,
                           coverage="object-table helicopters, bullets, power-ups and ground tanks; other hazards unknown")
                for track in obs["tracks"]:
                    track_key = (track["slot"], track["generation"])
                    if track_key in seen_tracks or track["phase"] != "observed_moving_signature":
                        continue
                    seen_tracks.add(track_key)
                    # Where objects actually appear, counted live rather than assumed.
                    edge = next((name for hit, name in ((track["x"] >= 240, "right"), (track["x"] <= 16, "left"),
                                 (track["y"] <= 48, "top"), (track["y"] >= 191, "bottom")) if hit), None)
                    if edge:
                        entry_edges[edge] = entry_edges.get(edge, 0)+1
                # Every decision is judged fresh, so nothing tells the aircraft it has been
                # camped on one side for the last few seconds. Runs that drifted to either
                # extreme scored worst, so where it has actually been is a fact worth having.
                recent_positions.append((state["frame"], obs["player"]["x"], obs["player"]["y"]))
                while recent_positions and state["frame"]-recent_positions[0][0] > 300:
                    recent_positions.pop(0)
                digest = combat_digest(obs, horizon=interval, entry_edges=entry_edges,
                                       recent_positions=recent_positions, recent_body_gaps=recent_body_gaps)
                # Lingering inside the range where collisions have happened is only visible
                # over several decisions: R20 sat at 20-21 px from a tank for four in a row.
                staying = (digest["actions"].get("hold") or {}).get("enemy_body_anchor_gap_px")
                recent_body_gaps.append((state["frame"], staying))
                while recent_body_gaps and state["frame"]-recent_body_gaps[0][0] > 300:
                    recent_body_gaps.pop(0)
                digest["recent_entry_edges"] = dict(entry_edges)
                states.write(json.dumps({"state":state,"observation":obs})+"\n"); states.flush()
                if not digest["player_position_supported"]:
                    reason="player_reference_outside_validated_bounds"; break
                if last_command and state.get("last_applied_run_id") == run_id and state.get("last_applied_call") == last_command["call"]:
                    if last_command["call"] not in acknowledged:
                        acknowledged.add(last_command["call"])
                        applied_jev += last_command["decision_source"] == "jev"
                        log("input_ack", command_id=last_command["call"], attempt=last_command["attempt"],
                            decision_source=last_command["decision_source"], first_apply_frame=state["first_apply_frame"],
                            observe_to_apply_frames=state["first_apply_frame"]-last_command["observed_frame"],
                            issue_to_apply_frames=state["first_apply_frame"]-last_command["issued_at_frame"], resulting_state=state)
                if last_frame >= stop_frame:
                    reason="game_frame_budget"; break
                if pending and pending["future"].done():
                    response, latency = pending["future"].result()
                    previous = pending["state"]
                    log("response", attempt=pending["attempt"], source_frame=previous["frame"], received_frame=last_frame,
                        latency_ms=latency, response=response, decision_source="jev" if mode=="live" else "deterministic_mock")
                    if not reply_is_fresh(previous,state,max_age):
                        reason="stale_reply_rejected"
                        log(reason, age_frames=last_frame-previous["frame"], max_age_frames=max_age,
                            requested_action=response["choice"], applied_action=None)
                        break
                    command(state,response["choice"],True,"jev" if mode=="live" else "deterministic_mock",pending["attempt"],previous)
                    print(f"{'Jev' if mode=='live' else 'MOCK'} {decisions}/{limit}: {response['choice']} + Y fire; {latency:.0f} ms; state age {last_frame-previous['frame']} game frames",flush=True)
                    pending = None
                if decisions >= limit and mode != "baseline" and pending is None and last_command:
                    if (last_command["call"] in acknowledged and state["first_apply_frame"]+interval <= last_frame):
                        reason="decision_budget"; break
                    time.sleep(0.005); continue
                if last_frame < decision_start:
                    # Re-issue before the lease expires, without rewriting the file every frame.
                    # A command issued on the frame before a pause is superseded before Lua reads it.
                    due = not last_command or last_frame-last_command["issued_at_frame"] >= max(5, interval-5)
                    if due and not (stepping and last_frame+1 >= decision_start):
                        command(state,"hold",prelude_fire,"deterministic_firing_prelude" if prelude_fire else "deterministic_neutral_prelude",
                                freeze_at=decision_start if stepping else 0)
                elif mode == "baseline":
                    if not last_command["fire"] or last_frame-last_command["issued_at_frame"] >= max(5, interval-5):
                        command(state,"hold",True,"firing_only_baseline")
                elif stepping:
                    if last_frame >= next_step:
                        observed = wait_for_freeze(last_frame)
                        if observed is None:
                            reason="freeze_not_confirmed"
                            log(reason, frame=last_frame); break
                        if not digest["continuous_track_count"]:
                            # Nothing checked to judge: keep firing and look again shortly.
                            next_step = last_frame+recheck
                            command(observed,"hold",True,"firing_only_no_verified_tracks",
                                    freeze_at=next_step if next_step < stop_frame else 0)
                            time.sleep(0.005); continue
                        if first_request is None:
                            first_request=last_frame
                        body = combat_request(digest)
                        decisions += 1
                        requests += mode=="live"  # Count attempts, including HTTP errors; no retries.
                        log("request" if mode=="live" else "mock_request", attempt=decisions, jev_requests=requests,
                            observed_state=observed, observation=obs, digest=digest, request_body=body, decision_timing="pause_and_step",
                            interval_since_previous_request_frames=None if last_preview_frame is None else last_frame-last_preview_frame)
                        last_preview_frame=last_frame
                        response, latency = decide(body,mode,decisions,key,delay_ms)
                        current = None
                        while current is None:
                            current = bridge.read_state()
                        progress = time.monotonic()
                        log("response", attempt=decisions, source_frame=observed["frame"], received_frame=current["frame"],
                            latency_ms=latency, response=response, decision_source="jev" if mode=="live" else "deterministic_mock",
                            frozen_throughout=current["frame"] == observed["frame"] and current.get("frozen") is True)
                        if not reply_is_fresh(observed,current,max_age):
                            reason="stale_reply_rejected"
                            log(reason, age_frames=current["frame"]-observed["frame"], max_age_frames=max_age,
                                requested_action=response["choice"], applied_action=None)
                            break
                        next_step = last_frame+interval
                        more = decisions < limit and next_step < stop_frame
                        command(current,response["choice"],True,"jev" if mode=="live" else "deterministic_mock",decisions,observed,
                                freeze_at=next_step if more else 0)
                        last_decision = {"frame":last_frame,"call":last_command["call"],"action":response["choice"],
                                         "gap":threat_gap(digest,response["choice"])}
                        print(f"{'Jev' if mode=='live' else 'MOCK'} {decisions}/{limit}: {response['choice']} + Y fire; {latency:.0f} ms; "
                              f"game frames elapsed while deciding {current['frame']-observed['frame']}",flush=True)
                    elif (last_decision and decisions < limit and last_command["call"] == last_decision["call"]
                          and last_frame-last_decision["frame"] >= replan_after):
                        # A threat that appeared or closed in since the decision: pause next frame and ask again.
                        gap = threat_gap(digest,last_decision["action"])
                        # Relative change only: a threat appeared where none was tracked, or the gap halved.
                        if gap is not None and (last_decision["gap"] is None or gap < last_decision["gap"]/2):
                            next_step = last_frame+1
                            last_command = dict(last_command,freeze_at_frame=next_step)
                            bridge.write_json(bridge.ACTION,last_command)
                            log("replan_trigger",frame=last_frame,action=last_decision["action"],gap_px=gap,
                                gap_at_decision_px=last_decision["gap"],decision_frame=last_decision["frame"])
                            last_decision = None
                elif pending is None and (last_preview_frame is None or last_frame-last_preview_frame >= interval):
                    if not digest["continuous_track_count"]:
                        # Do not silently shorten a model choice just because
                        # the current observation temporarily has no checked track.
                        if (last_command["decision_source"] in ("jev","deterministic_mock")
                                and last_command["call"] in acknowledged
                                and last_frame < state["first_apply_frame"]+interval):
                            time.sleep(0.005); continue
                        if not last_command["fire"] or last_frame-last_command["issued_at_frame"] >= max(5, interval-5):
                            command(state,"hold",True,"firing_only_no_verified_tracks")
                        time.sleep(0.005); continue
                    if first_request is None:
                        first_request=last_frame
                        command(state,"hold",True,"firing_only_waiting_for_first_choice")
                    body = combat_request(digest)
                    decisions += 1
                    requests += mode=="live"  # Count attempts, including HTTP errors; no retries.
                    log("request" if mode=="live" else "mock_request", attempt=decisions, jev_requests=requests,
                        observed_state=state, observation=obs, digest=digest, request_body=body,
                        interval_since_previous_request_frames=None if last_preview_frame is None else last_frame-last_preview_frame)
                    pending = {"state":state,"attempt":decisions,
                               "future":executor.submit(decide,body,mode,decisions,key,delay_ms)}
                    last_preview_frame=last_frame
                if last_command and last_command["call"] not in acknowledged and last_frame-last_command["issued_at_frame"] > 4:
                    raise TimeoutError("Controller command was not acknowledged")
                time.sleep(0.005)
        except (KeyboardInterrupt,InterruptedError):
            # Keep a reason the guard already set; only the default is a user stop.
            reason = "user_stop" if reason == "unknown" else reason
        except Exception as exc:
            reason="error"
            # Type and source location only; never the message, which could quote a response.
            spot=traceback.extract_tb(exc.__traceback__)[-1]
            detail=(f"{type(exc).__name__} at {Path(spot.filename).name}:{spot.lineno}"
                    + (f" HTTP {exc.code}" if hasattr(exc,"code") else ""))
            log("error", detail=detail, jev_requests=requests)
            print(f"Stopping safely: {detail}",flush=True)
        finally:
            bridge.release_controls(run_id,command_id)
            executor.shutdown(wait=True,cancel_futures=True)
            # A run can stop while HTTP is in flight. Preserve its eventual
            # typed result without ever injecting it after STOP or retrying it.
            if pending and pending["future"].done():
                try:
                    response,latency=pending["future"].result()
                    log("discarded_response_after_stop",attempt=pending["attempt"],
                        source_frame=pending["state"]["frame"],stopped_frame=last_frame,
                        latency_ms=latency,response=response,applied_action=None,stop_reason=reason)
                except Exception as exc:
                    log("discarded_request_error_after_stop",attempt=pending["attempt"],
                        detail=type(exc).__name__,applied_action=None,stop_reason=reason)
            report={"run_id":run_id,"mode":mode,"reason":reason,"jev_requests":requests,
                    "decisions":decisions,"applied_jev_decisions":applied_jev,"commands":command_id,
                    "final_frame":last_frame,"first_request_frame":first_request,
                    "wall_seconds":round(time.monotonic()-wall_start,3),"level_clear":None,
                    "health_damage_death":None,"stop_command_sent":True}
            log("finished",**{k:v for k,v in report.items() if k!="run_id"})
            (output / "summary.json").write_text(json.dumps(report,indent=2)+"\n")
            print(json.dumps(report),flush=True)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--mode",choices=("dry","live","baseline"),default="dry")
    ap.add_argument("--max-calls",type=int,default=5)
    ap.add_argument("--expected-start-frame",type=int,default=SAVE_FRAME,
                    help="frame the loaded save resumes at; slot 2 resumes at the boss")
    ap.add_argument("--warmup",type=int,default=480)
    ap.add_argument("--frames",type=int,default=210)
    ap.add_argument("--mock-delay-ms",type=int,default=250)
    ap.add_argument("--interval",type=int,default=30,help="game frames between decisions (also the forecast horizon)")
    ap.add_argument("--stepped",action="store_true",help="pause the emulator on each decision frame (pause-and-step)")
    ap.add_argument("--prelude-fire",action="store_true",help="Y firing during the prelude instead of gun off")
    args=ap.parse_args()
    if not 1 <= args.max_calls <= 2600 or not 0 <= args.warmup <= 900 or not 1 <= args.frames <= 7200:
        ap.error("Run budgets out of range")
    if not 1 <= args.interval <= 30:
        ap.error("Decision interval must be 1..30 game frames")
    output=args.output.resolve()
    if not output.is_relative_to(ROOT / "runs") or output==ROOT / "runs" or not output.is_dir():
        ap.error("Expected a unique existing run directory")
    key=None
    if args.mode=="live":
        # Reuse Carl's intentionally local file. Never copy it into manifests/env/logs.
        try:
            key=(ROOT / "typesafe_api_key.txt").read_text(encoding="utf-8-sig").strip()
        except (OSError,UnicodeError):
            raise SystemExit("Could not read the local key file; nothing was sent") from None
        if not key or "\n" in key or "\r" in key:
            raise SystemExit("Local key file must contain one key line; nothing was sent")
    result=run(output,args.mode,args.max_calls,interval=args.interval,warmup=args.warmup,frame_budget=args.frames,
               delay_ms=args.mock_delay_ms,key=key,stepped=args.stepped,prelude_fire=args.prelude_fire,
               expected_start=args.expected_start_frame)
    if result["reason"] not in ("decision_budget","game_frame_budget"):
        raise SystemExit(1)


if __name__=="__main__":
    main()
