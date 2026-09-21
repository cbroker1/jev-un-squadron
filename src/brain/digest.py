"""Numeric action consequences. All distances are between RAM reference points.

There are no guessed collision boxes, health rules, or model-confidence safety scores.
The movement model is measured in cardinal probes on the current pilot/save only.
"""
import math

ACTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0), "hold": (0, 0)}
CARDINAL_SPEED = 2.5
# Measured in four independent 120-frame held-direction probes on slot 1.
# These are limits of the player reference point, NOT collision boxes.
PLAYER_BOUNDS = (16, 239, 48, 191)


def player_position(px, py, dx, dy, at):
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    return max(xmin, min(xmax, px+dx*CARDINAL_SPEED*at)), max(ymin, min(ymax, py+dy*CARDINAL_SPEED*at))


def bounded_approach(px, py, dx, dy, projectile, horizon):
    """Closest RAM-anchor distance, splitting the path when movement hits a bound."""
    times = {0, horizon}
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    for position, direction, low, high in ((px, dx, xmin, xmax), (py, dy, ymin, ymax)):
        if direction:
            hit = ((high if direction > 0 else low)-position)/(direction*CARDINAL_SPEED)
            if 0 < hit < horizon:
                times.add(hit)
    times = sorted(times)
    best = (float("inf"), 0)
    for begin, end in zip(times, times[1:]):
        x, y = player_position(px, py, dx, dy, begin)
        ex, ey = player_position(px, py, dx, dy, end)
        vx = projectile["vx"] - (ex-x)/(end-begin)
        vy = projectile["vy"] - (ey-y)/(end-begin)
        rx = projectile["x"] + projectile["vx"]*begin - x
        ry = projectile["y"] + projectile["vy"]*begin - y
        distance, offset = nearest_approach(rx, ry, vx, vy, end-begin)
        best = min(best, (distance, begin+offset))
    return best


def nearest_approach(rx, ry, vx, vy, horizon):
    speed_squared = vx*vx + vy*vy
    t = max(0, min(horizon, -(rx*vx + ry*vy)/speed_squared)) if speed_squared else 0
    return math.hypot(rx+vx*t, ry+vy*t), t


def direction_words(dx, dy):
    horizontal = "right" if dx > 2 else "left" if dx < -2 else "aligned horizontally"
    vertical = "below" if dy > 2 else "above" if dy < -2 else "level"
    return vertical + ", " + horizontal


def summarize(obs, horizon_frames=20):
    if not 1 <= horizon_frames <= 30:
        raise ValueError("Research forecast horizon must be 1..30 game frames")
    px, py = obs["player"]["x"], obs["player"]["y"]
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    supported = xmin <= px <= xmax and ymin <= py <= ymax
    # Objects just past an edge (entering or leaving) still count: sprites extend past references.
    tracks = [t for t in obs["tracks"] if t["phase"] == "observed_moving_signature" and t.get("in_play", t["on_screen"])]
    forecasts = {}
    for action, (dx, dy) in ACTIONS.items():
        details = []
        for t in tracks:
            if not supported or t["vx"] is None or t["vy"] is None:
                continue
            rx, ry = t["x"]-px, t["y"]-py
            vx, vy = t["vx"]-dx*CARDINAL_SPEED, t["vy"]-dy*CARDINAL_SPEED
            distance, at_frame = bounded_approach(px, py, dx, dy, t, horizon_frames)
            details.append({"slot": t["slot"], "track_generation": t["generation"], "relative_direction": direction_words(rx, ry),
                            "closest_anchor_distance_px": round(distance, 3),
                            "closest_at_frame_offset": round(at_frame, 3),
                            "initial_anchor_distance_px": round(math.hypot(rx, ry), 3),
                            "initially_closing": rx*vx+ry*vy < 0})
        end_x, end_y = player_position(px, py, dx, dy, horizon_frames)
        margin = min(end_x-xmin, xmax-end_x, end_y-ymin, ymax-end_y)
        # "Room" is a planning description using one action's measured travel,
        # not a collision-size or invulnerability assumption.
        room = "at a movement limit" if margin == 0 else "less than one action of room to the nearest movement limit" if margin < CARDINAL_SPEED*horizon_frames else "at least one action of room to every movement limit"
        forecasts[action] = {"projected_position": [end_x, end_y] if supported else None,
                             "boundary_margin_px": margin if supported else None,
                             "room_description": room if supported else "player reference is outside validated movement bounds",
                             "tracked_projectiles": details,
                             "closest_anchor_distance_px": min((d["closest_anchor_distance_px"] for d in details), default=None)}
    distances = [f["closest_anchor_distance_px"] for f in forecasts.values() if f["closest_anchor_distance_px"] is not None]
    for action, forecast in forecasts.items():
        distance = forecast["closest_anchor_distance_px"]
        if distance is None:
            comparison = "No current, continuous on-screen projectile track to compare; this does not mean the route is clear."
        elif max(distances)-min(distances) <= 2:
            comparison = "Projected separation is similar across the offered actions."
        elif distance >= max(distances)-2:
            comparison = "Among the widest projected separations from the tracked projectiles."
        elif distance <= min(distances)+2:
            comparison = "Among the narrowest projected separations from the tracked projectiles."
        else:
            comparison = "Intermediate projected separation from the tracked projectiles."
        forecast["description"] = (("No directional buttons. " if action == "hold" else "Move " + action + ". ")
                                   + comparison + " Ends " + forecast["room_description"] + ".")
    return {"source_frame": obs["source_frame"], "horizon_frames": horizon_frames,
            "positive_y_direction": "down", "actions": forecasts,
            "tracked_locations": [direction_words(t["x"]-px, t["y"]-py) for t in tracks],
            "unknowns": ["other enemies and projectiles", "terrain",
                         "collision geometry and collision probability", "health and liveness", "firing alignment"],
            "forecast_assumptions": ["constant measured cardinal speed, current pilot/save only",
                                     "constant recent projectile velocity", "measured player bounds for this save; no collision simulation"],
            "player_position_supported": supported,
            "live_control_ready": False}
