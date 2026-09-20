"""Watch the existing main.lua bridge and preview Choice inputs, with ZERO API calls.

This is passive: no movement/fire actions are written. Physical play stays with
the user. STOP handshake clears old injection; frame/epoch changes end the run.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
import uuid

import bridge
from brain.observations import FamilyTracker, bridge_observation
from brain.digest import summarize
from brain.questions import movement_request

ROOT = Path(__file__).resolve().parent


def watch(output, frames, interval):
    run_id = output.name
    bridge.release_controls(run_id, 0)
    fresh = bridge.wait_for_fresh_state(run_id)
    tracker = FamilyTracker()
    last_frame, last_preview = None, None
    progress = time.monotonic()
    wall_start = progress
    counts = {"observations": 0, "previews": 0, "frames_with_velocity": 0,
              "max_gap_frames": 0, "nonzero_injected_observations": 0}
    reason = "unknown"
    previous_state = fresh
    with (output / "brain_stream.jsonl").open("x", encoding="utf-8") as log:
        while True:
            if (ROOT / "STOP").exists():
                reason = "project_stop"; break
            state = bridge.read_state()
            if state and state.get("bridge_run_id") != run_id:
                raise ValueError("Another bridge took control; ending passive preview")
            if state and (state.get("lua_session_id") != fresh["lua_session_id"] or
                          state.get("reload_epoch") != fresh["reload_epoch"] or
                          (last_frame is not None and state["frame"] < last_frame)):
                reason = "reload_or_session_change"; break
            if state and state["frame"] != last_frame:
                observed = bridge_observation(state, tracker)
                image = output / f"brain_frame_{state['frame']}.png"
                observed["screenshot"] = image.name if image.is_file() else None
                gap = 0 if last_frame is None else state["frame"]-last_frame
                counts["max_gap_frames"] = max(counts["max_gap_frames"], gap)
                counts["observations"] += 1
                counts["frames_with_velocity"] += any(t["on_screen"] and t["vx"] is not None for t in observed["tracks"])
                counts["nonzero_injected_observations"] += state["requested_mask"] != 0
                record = {"event": "observation", "observed_state": observed,
                    "decision_source": "not_requested", "requested_action": None,
                    "applied_action": None, "jev_requests": 0}
                if last_preview is None or state["frame"]-last_preview >= interval:
                    digest = summarize(observed)
                    record.update(projection=digest, request_preview=movement_request(digest),
                        interval_since_previous_preview_frames=None if last_preview is None else state["frame"]-last_preview)
                    last_preview = state["frame"]
                    counts["previews"] += 1
                log.write(json.dumps(record)+"\n")
                log.flush()
                last_frame = state["frame"]
                previous_state = state
                progress = time.monotonic()
                if last_frame-fresh["frame"] >= frames:
                    reason = "frame_budget"; break
            if time.monotonic()-progress > 3 or time.monotonic()-wall_start > 90:
                raise TimeoutError("Passive preview lost frame progress or exceeded wall budget")
            time.sleep(0.005)
    report = {"run_id": run_id, "reason": reason, "start_frame": fresh["frame"],
              "end_frame": previous_state["frame"], "preview_interval_target_frames": interval,
              "wall_seconds": round(time.monotonic()-wall_start, 3),
              **counts, "jev_requests": 0, "movement_or_fire_commands": 0,
              "controller_note": "STOP handshake only; no ongoing injected movement/fire; human input is allowed"}
    (output / "brain_validation.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=int, default=900)
    ap.add_argument("--interval", type=int, default=30, help="preview spacing in observed GAME frames")
    ap.add_argument("--output", type=Path, help="existing unique runner folder under runs")
    args = ap.parse_args()
    if not 1 <= args.frames <= 1800 or not 1 <= args.interval <= 120:
        ap.error("Frames must be 1..1800 and preview interval 1..120")
    output = args.output or ROOT / "runs" / ("brain-observe-"+dt.datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6])
    output = output.resolve()
    if not output.is_relative_to(ROOT / "runs") or output == ROOT / "runs":
        ap.error("Output must be a run-specific folder under runs")
    output.mkdir(exist_ok=True)
    print(f"Passive brain preview: {output.name}. Jev calls: 0. Ctrl+C stops.", flush=True)
    try:
        watch(output, args.frames, args.interval)
    finally:
        # Never interfere with a newer bridge if it took over while observing.
        state = bridge.read_state()
        if not state or state.get("bridge_run_id") == output.name:
            bridge.release_controls(output.name, 0)


if __name__ == "__main__":
    main()
