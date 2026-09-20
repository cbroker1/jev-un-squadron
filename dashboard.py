"""Jev Squadron: a local dashboard for watching a run and reading its history.

Serves 127.0.0.1 only and reads the same run files everything else writes, so it
holds no state of its own, needs no hook into the controller, and can be left open
across runs: it follows runs/active_segment.json and switches over by itself.

Nothing here talks to Jev, touches the emulator, or reads credentials.
"""
import argparse
import json
import statistics
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
DECISION_START = 20663          # the frame Jev takes over, from the save state
KINDS = ("enemy_aircraft", "hostile_projectile", "power_up", "clear_screen_power_up",
         "ground_tank", "turret")


def tail_events(path, wanted, limit):
    """The last `limit` events of the wanted kinds, without holding the file open."""
    if not path.exists():
        return []
    # Runs are a few MB at most; reading the tail is simpler than tracking offsets
    # and cannot drift out of step when a run restarts.
    lines = path.read_text(errors="replace").splitlines()
    found = []
    for line in reversed(lines):
        if len(found) >= limit:
            break
        if not any(f'"event": "{kind}"' in line for kind in wanted):
            continue
        try:
            found.append(json.loads(line))
        except ValueError:                  # the writer may be mid-line
            continue
    return list(reversed(found))


def option_story(digest, action):
    """What the chosen option is actually pursuing, read off its own measured facts.

    Derived from the numbers Jev was given; it is not a second question put to Jev.
    """
    option = (digest.get("actions") or {}).get(action)
    if not option:
        return []
    story = []
    if option.get("targets_the_gun_would_hit"):
        story.append(("SHOT", f"{option['targets_the_gun_would_hit']} target(s), soonest a "
                              f"{str(option.get('soonest_hit_kind') or '').replace('_', ' ')} in "
                              f"{option.get('soonest_hit_frames')} frames"))
    elif option.get("aim_error_px") is not None:
        story.append(("AIM", f"{option['aim_error_px']:.0f} px off the gun line"))
    if option.get("clear_screen_power_up_closest_px") is not None:
        story.append(("CLEAR-ALL", f"{option['clear_screen_power_up_closest_px']:.0f} px away, "
                                   f"{option.get('frames_to_reach_clear_screen_power_up')} frames of flying, "
                                   f"gone in {option.get('frames_until_clear_screen_power_up_leaves_play')}"))
    if option.get("power_up_closest_px") is not None:
        story.append(("POWER-UP", f"{option['power_up_closest_px']:.0f} px away, "
                                  f"{option.get('frames_to_reach_power_up')} frames of flying"))
    if option.get("targets_behind"):
        cost = option.get("frames_to_get_behind_nearest_target_behind")
        story.append(("BEHIND", f"{option['targets_behind']} back, nearest is a "
                                f"{str(option.get('nearest_target_behind_kind') or '').replace('_', ' ')}"
                                + (f", {cost} frames to get past" if cost else ", cannot be caught")))
    if option.get("targets_that_will_slip_behind_you"):
        story.append(("SLIPPING", f"{option['targets_that_will_slip_behind_you']} will pass behind in "
                                  f"{option.get('first_slips_behind_in_frames')} frames"))
    if option.get("ends_at_or_below_terrain"):
        story.append(("TERRAIN", f"ends at or below a recorded collision altitude "
                                 f"(Y {option.get('terrain_floor_y')})"))
    threat = option.get("closest_anchor_distance_px")
    body = option.get("enemy_body_anchor_gap_px")
    gaps = [g for g in (threat, body) if g is not None]
    if gaps:
        story.append(("CLOSEST", f"{min(gaps):.0f} px {option.get('closest_threat_direction') or ''}".strip()))
    return story


def live_state():
    """Everything the page shows for the run happening right now."""
    pointer = RUNS / "active_segment.json"
    if not pointer.exists():
        return {"running": False}
    try:
        active = json.loads(pointer.read_text())
    except ValueError:
        return {"running": False}
    run_dir = Path(active.get("run_dir", ""))
    if not run_dir.exists():
        return {"running": False}
    manifest = {}
    if (run_dir / "manifest.json").exists():
        try:
            manifest = json.loads((run_dir / "manifest.json").read_text())
        except ValueError:
            manifest = {}
    events = tail_events(run_dir / "events.jsonl", ("request", "response", "finished"), 60)
    requests = [e for e in events if e["event"] == "request"]
    responses = [e for e in events if e["event"] == "response"]
    finished = next((e for e in events if e["event"] == "finished"), None)
    latest = requests[-1] if requests else None
    observation = latest.get("observation") if latest else None
    digest = latest.get("digest") if latest else None
    by_frame = {r["source_frame"]: r for r in responses}
    feed = []
    for request in requests[-14:]:
        frame = request["observation"]["source_frame"]
        answer = by_frame.get(frame)
        reply = (answer or {}).get("response") or {}
        feed.append({
            "attempt": request.get("attempt"), "frame": frame,
            "choice": reply.get("choice"), "confidence": reply.get("confidence"),
            "probabilities": reply.get("probabilities") or {},
            "latency_ms": (answer or {}).get("latency_ms"),
            "source": (answer or {}).get("decision_source"),
            "story": option_story(request.get("digest") or {}, reply.get("choice") or ""),
        })
    tracks = []
    if observation:
        for track in observation.get("tracks", []):
            if track.get("kind") in KINDS and track.get("phase") == "observed_moving_signature":
                tracks.append({"kind": track["kind"], "x": track["x"], "y": track["y"],
                               "vx": track.get("vx"), "vy": track.get("vy")})
    chosen = feed[-1] if feed else {}
    return {
        "running": bool(active.get("running")) and not finished,
        "run_label": manifest.get("run_label"), "run_id": run_dir.name,
        "mode": manifest.get("mode"), "frame": observation["source_frame"] if observation else None,
        "decision_start_frame": DECISION_START,
        "player": (observation or {}).get("player"),
        "scroll_x": (observation or {}).get("scroll_x"),
        "tracks": tracks,
        "counts": {kind: sum(t["kind"] == kind for t in tracks) for kind in KINDS},
        "feed": feed,
        "judgment": {"question": "MOVEMENT", "asked": "Which movement should the aircraft make now?",
                     "probabilities": chosen.get("probabilities") or {},
                     "confidence": chosen.get("confidence"), "choice": chosen.get("choice")},
        "station": (digest or {}).get("where_you_have_been_recently"),
        "terrain_note": (digest or {}).get("terrain_constraint_suspended"),
        "finished": finished,
    }


@lru_cache(maxsize=256)
def _run_row(name, stamp):
    """One history row. Cached on the run's own mtime, so finished runs parse once."""
    run = RUNS / name
    summary = json.loads((run / "summary.json").read_text())
    row = {"run_id": name, "mode": summary.get("mode"), "reason": summary.get("reason"),
           "requests": summary.get("jev_requests"), "final_frame": summary.get("final_frame"),
           "wall_seconds": summary.get("wall_seconds"), "label": None,
           "kills": None, "air": None, "tank": None, "turret": None, "hits": None,
           "hit_causes": [], "pickups": None, "median_x": None, "passed": None}
    if (run / "manifest.json").exists():
        try:
            row["label"] = json.loads((run / "manifest.json").read_text()).get("run_label")
        except ValueError:
            pass
    if (run / "validation.json").exists():
        try:
            row["passed"] = json.loads((run / "validation.json").read_text()).get("pass")
        except ValueError:
            pass
    trace = run / "decision_trace.json"
    if trace.exists():
        try:
            data = json.loads(trace.read_text())
        except ValueError:
            return row
        events = data.get("candidate_table_events") or {}
        after = lambda key: len([x for x in events.get(key, []) if x["frame"] > DECISION_START])
        row["air"], row["tank"], row["turret"] = (after("aircraft_destroyed"), after("tanks_destroyed"),
                                                  after("turrets_destroyed"))
        row["kills"] = row["air"] + row["tank"] + row["turret"]
        row["hits"] = len(events.get("hit_marker_frames") or [])
        row["hit_causes"] = [c["likely"] if c["likely"] == "unidentified" else c["likely"][0]["kind"]
                             for c in events.get("hit_causes", [])]
        row["pickups"] = len(events.get("power_up_gone_near_player") or [])
        xs = [t["observed_player_xy"][0] for t in data.get("trace", []) if t.get("observed_player_xy")]
        row["median_x"] = round(statistics.median(xs)) if xs else None
    return row


def history(limit=40):
    rows = []
    for run in sorted(RUNS.glob("combat-*"), reverse=True)[:limit]:
        if not (run / "summary.json").exists():
            continue
        try:
            stamp = max((run / name).stat().st_mtime
                        for name in ("summary.json", "decision_trace.json")
                        if (run / name).exists())
            rows.append(_run_row(run.name, stamp))
        except (OSError, ValueError, KeyError):
            continue
    return rows


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):        # the page polls constantly; no console spam
        pass

    def send_payload(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path.startswith("/api/live"):
                self.send_payload(json.dumps(live_state()).encode(), "application/json")
            elif self.path.startswith("/api/runs"):
                self.send_payload(json.dumps({"runs": history()}).encode(), "application/json")
            elif self.path in ("/", "/index.html"):
                self.send_payload((ROOT / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionAbortedError):
            pass                              # the page reloaded mid-poll
        except Exception as error:            # a dashboard must never take a run down
            self.send_payload(json.dumps({"error": f"{type(error).__name__}: {error}"}).encode(),
                              "application/json")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Jev Squadron on http://127.0.0.1:{args.port}  (Ctrl+C stops; leave it open across runs)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
