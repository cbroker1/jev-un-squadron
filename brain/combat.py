"""Limited experimental combat summaries. Reference gaps are not collision clearance."""
import json
from pathlib import Path

from .digest import ACTIONS, PLAYER_BOUNDS, direction_words, nearest_approach, summarize

TERRAIN_MAP = Path(__file__).resolve().parent.parent / "terrain_map.json"
_terrain = None


def terrain_columns():
    """Measured terrain map from past runs, keyed by level column; empty when absent."""
    global _terrain
    if _terrain is None:
        try:
            data = json.loads(TERRAIN_MAP.read_text())
            _terrain = ({int(k): v for k, v in data["columns"].items()}, data.get("bucket_px", 4))
        except (OSError, ValueError, KeyError):
            _terrain = ({}, 4)
    return _terrain


def terrain_at(position, scroll, spread=2):
    """(altitude of a recorded terrain hit, lowest altitude flown safely) near a position."""
    columns, bucket = terrain_columns()
    if not columns or scroll is None or not position:
        return None, None, None
    centre = int((position[0]+scroll)//bucket)
    hit = safe = ground = None
    for column in range(centre-spread, centre+spread+1):
        entry = columns.get(column)
        if not entry:
            continue
        if entry.get("hit_min_y") is not None:
            hit = entry["hit_min_y"] if hit is None else min(hit, entry["hit_min_y"])
        if entry.get("safe_max_y") is not None:
            safe = entry["safe_max_y"] if safe is None else max(safe, entry["safe_max_y"])
        if entry.get("ground_object_y") is not None:
            ground = entry["ground_object_y"] if ground is None else min(ground, entry["ground_object_y"])
    return hit, safe, ground


KINDS = ("hostile_projectile", "enemy_aircraft", "power_up", "ground_tank", "turret", "clear_screen_power_up")
TARGETS = ("enemy_aircraft", "ground_tank", "turret")
# Player shots travel right at exactly 11 px per game frame at the aircraft's own Y
# (420 measured steps). The vertical tolerance is estimated from two observed kills.
SHOT_SPEED = 11
SHOT_BAND = 10
SHOT_MAX_X = 251


def future_shots(position, targets, window=30, step=3):
    """Targets that will cross into the gun's line if the aircraft holds this position.

    Enemies keep moving, so a position's value is not only what it can hit now.
    Constant-velocity estimate over a short window; not a prediction of the level.
    """
    if not position:
        return 0, None
    px, py = position
    count, soonest = 0, None
    for target in targets:
        for frame in range(0, window+1, step):
            x = target["x"] + target["vx"]*frame
            if x <= px:
                break
            if abs(target["y"] + target["vy"]*frame - py) <= SHOT_BAND and (x-px)/SHOT_SPEED <= window:
                count += 1
                soonest = frame if soonest is None else min(soonest, frame)
                break
    return count, soonest


def aim_error(position, targets, horizon):
    """Vertical error to the nearest target a shot could reach if the aircraft were level with it."""
    if not position:
        return None
    px, py = position
    errors = []
    for target in targets:
        closing = SHOT_SPEED - target["vx"]
        if closing <= 0:
            continue
        travel = (target["x"] - px)/closing
        if not 0 <= travel <= horizon*4 or px + SHOT_SPEED*travel > SHOT_MAX_X:
            continue
        errors.append((round(abs(target["y"] + target["vy"]*travel - py), 1), round(travel, 1)))
    return min(errors) if errors else None


def shot_intersections(position, targets, horizon):
    """Targets a shot fired from `position` would meet, with the frames until it lands.

    Straight-line geometry from measured shot speed against each target's recent
    velocity. It is not a claim about hitboxes, firing cadence or damage.
    """
    if not position:
        return []
    px, py = position
    landings = []
    for target in targets:
        closing = SHOT_SPEED - target["vx"]
        if closing <= 0:
            continue
        travel = (target["x"] - px)/closing
        if not 0 <= travel <= horizon*4:
            continue
        meet_x = px + SHOT_SPEED*travel
        if meet_x > SHOT_MAX_X or abs(target["y"] + target["vy"]*travel - py) > SHOT_BAND:
            continue
        landings.append((round(travel, 1), target["kind"], round(meet_x)))
    return sorted(landings)


def warning_room(position, entries):
    """Distance from a position to the edge objects have actually been entering from."""
    if not position or not entries:
        return None, None
    edge = max(entries, key=entries.get)
    x, y = position
    return round({"right": 256-x, "left": x, "top": y, "bottom": 224-y}[edge], 1), edge


def retreat_room(position, entries):
    """Room left on the far side from where objects enter: the buffer to fall back into."""
    if not position or not entries:
        return None
    edge = max(entries, key=entries.get)
    x, y = position
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    return round({"right": x-xmin, "left": xmax-x, "top": ymax-y, "bottom": y-ymin}[edge], 1)


def field_forecast(targets, threats, window=30):
    """The whole flyable area, not just the next step: what each area offers and costs.

    For a coarse grid of positions the aircraft could work toward, this reports how many
    targets would cross the gun's line within the window if it sat there, and how close
    the nearest threat would come. Constant-velocity estimates over measured bounds.
    """
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    # Rows step about one gun band apart, or the map would miss every firing line.
    columns = [round(xmin+(xmax-xmin)*i/3) for i in range(4)]
    rows = [round(ymin+(ymax-ymin)*i/7) for i in range(8)]
    cells = []
    for y in rows:
        for x in columns:
            coming, soonest = future_shots([x, y], targets, window)
            gaps = [nearest_approach(t["x"]-x, t["y"]-y, t["vx"], t["vy"], window)[0] for t in threats]
            cells.append({"xy": [x, y], "targets_into_line": coming,
                          "first_in_frames": soonest, "nearest_threat_px": round(min(gaps), 1) if gaps else None})
    return cells


def combat_digest(obs, horizon=20, entry_edges=None, lookahead=30):
    tracks = {kind: [t for t in obs["tracks"] if t["kind"] == kind] for kind in KINDS}
    digest = summarize(dict(obs, tracks=tracks["hostile_projectile"]), horizon)
    # Tanks collide with the aircraft too (one observed collision), so they count as bodies.
    bodies = summarize(dict(obs, tracks=tracks["enemy_aircraft"]+tracks["ground_tank"]+tracks["turret"]), horizon)
    # Closest approach to a power-up uses the same geometry; smaller means collecting it.
    reach = summarize(dict(obs, tracks=tracks["power_up"]), horizon)
    clear_reach = summarize(dict(obs, tracks=tracks["clear_screen_power_up"]), horizon)
    live = [t for t in obs["tracks"] if t["phase"] == "observed_moving_signature"
            and t.get("in_play", t["on_screen"]) and t["vx"] is not None]
    count = lambda kind: sum(t["kind"] == kind for t in live)
    digest["continuous_track_count"] = len(live)
    digest["enemy_count"] = count("enemy_aircraft")
    digest["projectile_count"] = count("hostile_projectile")
    digest["power_up_count"] = count("power_up")
    digest["tank_count"] = count("ground_tank")
    digest["turret_count"] = count("turret")
    digest["clear_screen_power_up_count"] = count("clear_screen_power_up")
    digest["complete_hazard_coverage"] = False
    # Threats arrive from any direction; say where they are right now, not just how far.
    px, py = obs["player"]["x"], obs["player"]["y"]
    census = {}
    for t in live:
        if t["kind"] == "power_up":
            continue
        census[direction_words(t["x"]-px, t["y"]-py)] = census.get(direction_words(t["x"]-px, t["y"]-py), 0)+1
    digest["tracked_threats_by_direction"] = census
    digest["field_forecast"] = field_forecast([t for t in live if t["kind"] in TARGETS],
                                              [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")])
    for action, option in digest["actions"].items():
        option["enemy_body_anchor_gap_px"] = bodies["actions"][action]["closest_anchor_distance_px"]
        nearest = min(option["tracked_projectiles"]+bodies["actions"][action]["tracked_projectiles"],
                      key=lambda d: d["closest_anchor_distance_px"], default=None)
        option["closest_threat_direction"] = nearest["relative_direction"] if nearest else None
        option["power_up_closest_px"] = reach["actions"][action]["closest_anchor_distance_px"]
        option["clear_screen_power_up_closest_px"] = clear_reach["actions"][action]["closest_anchor_distance_px"]
        position = option["projected_position"]
        # A squeeze is only visible if the sides are reported separately.
        sides = {"ahead": [], "behind": []}
        for t in (live if position else []):
            if t["kind"] in ("power_up", "clear_screen_power_up"):
                continue
            fx, fy = t["x"]+t["vx"]*horizon, t["y"]+t["vy"]*horizon
            sides["ahead" if fx > position[0] else "behind"].append(((fx-position[0])**2+(fy-position[1])**2)**0.5)
        (option["terrain_hit_recorded_y"], option["lowest_safe_y_measured"],
         option["ground_object_y_here"]) = terrain_at(position, obs.get("scroll_x"))
        option["gap_ahead_px"] = round(min(sides["ahead"]), 1) if sides["ahead"] else None
        option["gap_behind_px"] = round(min(sides["behind"]), 1) if sides["behind"] else None
        # The main gun fires right along the aircraft's Y; only targets still ahead can be hit.
        def line_error(kind):
            errors = [abs(t["y"]+t["vy"]*horizon-position[1]) for t in live
                      if position and t["kind"] == kind and t["x"]+t["vx"]*horizon > position[0]]
            return round(min(errors), 1) if errors else None
        option["firing_alignment_error_px"] = line_error("enemy_aircraft")
        option["tank_firing_line_error_px"] = line_error("ground_tank")
        option["turret_firing_line_error_px"] = line_error("turret")
        reachable = [t for t in live if t["kind"] in TARGETS]
        landings = shot_intersections(position, reachable, horizon)
        aim = aim_error(position, reachable, horizon)
        option["aim_error_px"] = aim[0] if aim else None
        coming, soonest = future_shots(position, reachable)
        option["targets_entering_your_line_soon"] = coming
        option["first_such_target_in_frames"] = soonest
        # Shots only travel right, so targets ahead are the ones this position can cover.
        option["targets_ahead"] = sum(1 for t in reachable if position and t["x"]+t["vx"]*horizon > position[0])
        # The gun only fires right, so a target behind is attackable only after getting past it.
        behind = sorted(position[0]-(t["x"]+t["vx"]*horizon) for t in reachable
                        if position and t["x"]+t["vx"]*horizon <= position[0]) if position else []
        option["targets_behind"] = len(behind)
        option["pixels_to_pass_nearest_behind"] = round(behind[0], 1) if behind else None
        option["warning_room_px"], option["warning_room_edge"] = warning_room(position, entry_edges)
        option["retreat_room_px"] = retreat_room(position, entry_edges)
        # One action can look clear for its own frames and still end where something arrives soon.
        waits = [nearest_approach(t["x"]+t["vx"]*horizon-position[0], t["y"]+t["vy"]*horizon-position[1],
                                  t["vx"], t["vy"], lookahead)[0]
                 for t in live if t["kind"] != "power_up"] if position else []
        option["threat_gap_if_you_hold_px"] = round(min(waits), 1) if waits else None
        option["targets_the_gun_would_hit"] = len(landings)
        option["soonest_hit_frames"] = landings[0][0] if landings else None
        option["soonest_hit_kind"] = landings[0][1] if landings else None
    return digest


def closest_threat(option):
    """The one number that matters first: smallest projected gap to any tracked bullet, aircraft or tank."""
    gaps = [(g, name) for g, name in ((option["closest_anchor_distance_px"], "bullet"),
            (option["enemy_body_anchor_gap_px"], "aircraft or tank")) if g is not None]
    return min(gaps) if gaps else None


def edge_words(position):
    """Which movement limits an action ends on; limits are measured for this pilot/save."""
    if not position:
        return ""
    x, y = position
    edges = [name for hit, name in ((x >= 239, "the right edge"), (x <= 16, "the left edge"),
             (y <= 48, "the top edge"), (y >= 191, "the bottom edge")) if hit]
    return " Ends on " + " and ".join(edges) + "." if edges else ""


def describe_gap(value):
    return "none tracked" if value is None else f"{value:.1f} pixels"


def combat_request(digest, model="jev-latest"):
    criteria = {}
    for action, f in digest["actions"].items():
        if f["targets_the_gun_would_hit"]:
            shots = (f"the gun would hit {f['targets_the_gun_would_hit']} tracked target(s), soonest a "
                     f"{f['soonest_hit_kind'].replace('_', ' ')} in {f['soonest_hit_frames']:.0f} frames")
        elif f["aim_error_px"] is not None:
            shots = f"no hit yet; the nearest reachable target is {f['aim_error_px']:.0f} pixels off the gun line (smaller means lining up)"
        else:
            shots = "no tracked target the gun can reach"
        alignment = ("no tracked aircraft ahead to align with" if f["firing_alignment_error_px"] is None
                     else f"aircraft firing-line error {f['firing_alignment_error_px']:.1f} pixels (smaller is better)")
        clear_up = ("" if f["clear_screen_power_up_closest_px"] is None
                    else f"; closest approach to the screen-clearing power-up {f['clear_screen_power_up_closest_px']:.1f} pixels "
                         f"(touching it destroyed every live target in both observed pickups)")
        power_up = ("" if f["power_up_closest_px"] is None
                    else f"; closest approach to the power-up {f['power_up_closest_px']:.1f} pixels (touching collects it; the one observed pickup happened at about 18 pixels)")
        tanks = ("" if f["tank_firing_line_error_px"] is None
                 else f"; ground-tank firing-line error {f['tank_firing_line_error_px']:.1f} pixels (smaller lets the gun hit tanks)")
        turrets = ("" if f["turret_firing_line_error_px"] is None
                   else f"; turret firing-line error {f['turret_firing_line_error_px']:.1f} pixels")
        threat = closest_threat(f)
        # 22 px is the widest reference gap at which a recorded collision happened.
        where = f", {f['closest_threat_direction']}" if f["closest_threat_direction"] else ""
        closest = ("Closest tracked threat: none tracked. " if threat is None
                   else f"Closest tracked threat: {threat[0]:.1f} pixels ({threat[1]}{where})"
                        + (" - inside the range where collisions have happened. " if threat[0] <= 22 else ". "))
        coming = ("" if not f["targets_entering_your_line_soon"]
                  else f" Holding this position, {f['targets_entering_your_line_soon']} target(s) drift into the gun's line "
                       f"within the next minute of play, the first in about {f['first_such_target_in_frames']} frames.")
        ground = ""
        if f["ground_object_y_here"] is not None:
            ground += (f" Terrain: tanks or turrets stand at Y {f['ground_object_y_here']:.0f} here, so the solid "
                       f"surface is about that altitude.")
        if f["terrain_hit_recorded_y"] is not None:
            ground += f" A terrain collision was recorded here at Y {f['terrain_hit_recorded_y']:.0f} and below."
        elif f["lowest_safe_y_measured"] is not None:
            ground += f" The lowest altitude flown here without an untracked hit is Y {f['lowest_safe_y_measured']:.0f}."
        squeeze = ("" if f["gap_ahead_px"] is None and f["gap_behind_px"] is None
                   else f" Nearest threat ahead: {describe_gap(f['gap_ahead_px'])}; behind: {describe_gap(f['gap_behind_px'])}.")
        behind = ("" if not f["targets_behind"]
                  else f" Targets behind you: {f['targets_behind']} (nearest {f['pixels_to_pass_nearest_behind']:.0f} pixels back; "
                       f"slip past it and the gun can hit it).")
        room = ("" if f["warning_room_px"] is None
                else f" Targets ahead of you: {f['targets_ahead']}; room from the {f['warning_room_edge']} side, "
                     f"where objects have been entering: {f['warning_room_px']:.0f} pixels; room left to fall back "
                     f"away from that side: {f['retreat_room_px']:.0f} pixels.")
        later = ("" if f["threat_gap_if_you_hold_px"] is None
                 else f" Staying there afterwards, the nearest tracked threat closes to {f['threat_gap_if_you_hold_px']:.0f} pixels.")
        criteria[action] = (f"{'No directional buttons' if action == 'hold' else 'Move '+action}. {closest}"
            f"Attack: {shots}.{coming}{squeeze}{behind}{room}{later}{ground} "
            f"Bullet-reference gap: {describe_gap(f['closest_anchor_distance_px'])}; "
            f"aircraft/tank/turret-reference gap: {describe_gap(f['enemy_body_anchor_gap_px'])}; {alignment}{power_up}{clear_up}{tanks}{turrets}. "
            f"Ends at {f['projected_position'][0]:.0f},{f['projected_position'][1]:.0f}, {f['room_description']}."
            f"{edge_words(f['projected_position'])}" if f["projected_position"] else f"Ends {f['room_description']}.")
    return {"model": model, "state": {"experiment": "bounded_experimental_combat_not_level_clear",
        "goal": ("Destroy enemies and collect power-ups. The main gun fires to the right by itself, so steering decides "
                 "what it hits: put targets in the gun's path and take power-ups. Avoiding damage is the constraint on "
                 "how you attack, not the objective."),
        "coverage": ("Helicopters, enemy bullets (blue or orange), dropped power-ups and ground tanks anywhere in the "
                     "game's object table. Tanks and turrets collide with the aircraft. Terrain and the platforms structures sit "
                     "on are not tracked at all, and a recorded hit came from flying low beside a turret platform, so "
                     "'none tracked' is not a guarantee of safety."),
        "known_tracks": {"aircraft": digest["enemy_count"], "bullets": digest["projectile_count"],
                         "power_ups": digest["power_up_count"], "tanks": digest["tank_count"],
                         "turrets": digest["turret_count"], "screen_clearing_power_ups": digest["clear_screen_power_up_count"]},
        "action_horizon_game_frames": digest["horizon_frames"],
        # Counted in this run, not a rule: where tracked objects have appeared so far.
        "object_entries_counted_this_run": digest.get("recent_entry_edges") or "none counted yet",
        "tracked_threats_by_direction_now": digest.get("tracked_threats_by_direction") or "none tracked",
        "field_forecast_next_30_frames": digest.get("field_forecast"),
        "terrain": ("The ground and the platforms structures stand on are solid but are not tracked at all. Tracked tanks "
                    "and turrets sit on that terrain, so their altitude marks where it is. Every recorded collision with "
                    "terrain happened while flying at Y 174 to 191, with nothing tracked nearby. Where past runs measured "
                    "this stretch, each option says so; a column with no measurement is unknown, not safe."),
        "uncertainty": ("Gaps are between reference points, not hitboxes: every collision recorded so far happened at a "
                        "reference gap of 9 to 22 pixels, so a gap in that range is a hit, not clearance. Constant recent "
                        "velocity is a short-horizon estimate. Health and death are unknown.")},
        "questions": {"movement": {"type": "choice", "criteria": criteria,
            "instructions": ("Choose one movement. Enemies close in from any direction - ahead, behind, above and below - so read each "
                "option's closest threat and its direction rather than assuming danger comes from one side. Play to "
                "destroy targets and collect power-ups: prefer options whose "
                "Attack line puts tracked targets in the gun's path. Turrets are the highest-value target: destroying one drops a "
                "power-up, and more power-ups mean more firepower for the rest of the level, so take a turret when the "
                "closest threat allows. A screen-clearing power-up is worth more than any single kill because it destroys every "
                "live target at once, so go for it when the way there is clear and let it go when reaching it means "
                "crossing close threats. A target behind you cannot be shot until you get past it: when one is close "
                "behind and the way is clear, go around and take it rather than drifting away and letting it box you in. "
                "field_forecast_next_30_frames covers the whole flyable area, not just this step: for positions across the "
                "screen it gives the targets that would cross the gun's line within 30 frames and how close threats would "
                "come there. Work toward the areas that pay off over several moves instead of judging only the next one. "
                "Targets keep moving, so position is worth as much as an immediate shot: falling back to where targets will "
                "drift into your line is normal play, not a retreat, and it beats chasing them from behind where the gun "
                "cannot fire. When no option hits yet, prefer the one that most reduces "
                "the pixels off the gun line, so a shot lines up within the next few moves; also prefer options that close "
                "on a power-up. Keeping distance from the side objects enter from buys reaction time, and staying behind targets "
                "lets the gun cover more of the screen. Room to fall back into is about where to wait, not a no-go area: do not "
                "idle against the far bound with nothing behind you, but moving into that strip to take a shot, reach a "
                "power-up or kill something coming up behind you is the right move. Weaving between "
                "bullets to reach a firing position is the intended play. The constraint is the closest tracked threat: do "
                "not take an option whose closest threat is tight. Colliding with an aircraft, tank or turret is the main way this "
                "aircraft takes damage, so an option whose closest threat sits inside the collision range is a last resort. "
"When threats close from both sides at once, do not drift and let the gap shrink: take the option that "
                "opens the squeeze, going over or under if that is the side with room, and take the shot on the way out "
                "when one is offered. Watch the number for staying there afterwards too, because a "
                "move that is clear for its own few frames can still end where a tank, aircraft or bullet arrives moments "
                "later. An option "
                "that hits nothing, collects nothing and only keeps distance is a wasted move when a safer-or-equal option "
                "attacks. Ground tanks collide with the aircraft, so shoot them from a horizontal distance rather than "
                "descending onto them. Compare the "
                "already-computed consequences, not raw coordinates. Hold is an ordinary action, not an automatic safe "
                "fallback. New objects appear from off-screen without warning; object_entries_counted_this_run says where they "
                "have come from so far in this run. Health and model confidence must not be used to infer safety.")}}}
