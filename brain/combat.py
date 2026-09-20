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


def terrain_at(position, scroll, spread=2, span_from=None):
    """Terrain known near a position, covering every column the move crosses.

    Returns (the altitudes where collisions were actually recorded, the lowest altitude
    flown safely, surface altitude from tanks and turrets standing there).
    """
    columns, bucket = terrain_columns()
    # The scroll counter wraps once the level stops scrolling at the boss, so a huge value
    # means the level position is unknown, not that the aircraft is 65000 pixels along.
    if not columns or scroll is None or scroll > 60000 or not position:
        return None, None, None
    ends = sorted({int((position[0]+scroll)//bucket), int(((span_from if span_from is not None else position[0])+scroll)//bucket)})
    hit, safe, ground = set(), None, None
    for column in range(ends[0]-spread, ends[-1]+spread+1):
        entry = columns.get(column)
        if not entry:
            continue
        hit.update(entry.get("collision_altitudes")
                   or ([entry["hit_min_y"]] if entry.get("hit_min_y") is not None else []))
        if entry.get("safe_max_y") is not None:
            safe = entry["safe_max_y"] if safe is None else max(safe, entry["safe_max_y"])
        if entry.get("ground_object_y") is not None:
            ground = entry["ground_object_y"] if ground is None else min(ground, entry["ground_object_y"])
    return (sorted(hit) or None), safe, ground


def blocked_altitudes(position, scroll, spread=1, span_from=None):
    """Altitudes where our own shots stopped against something solid on this path.

    Shots travel right at a measured 11 px per frame; one that stops short of the screen
    edge with no visible target beside it has hit structure. This maps far more of the
    level than collisions do, because it costs nothing to measure.
    """
    columns, bucket = terrain_columns()
    if not columns or scroll is None or scroll > 60000 or not position:
        return None
    ends = sorted({int((position[0]+scroll)//bucket),
                   int(((span_from if span_from is not None else position[0])+scroll)//bucket)})
    found = set()
    for column in range(ends[0]-spread, ends[-1]+spread+1):
        found.update((columns.get(column) or {}).get("shots_stopped_at") or ())
    return sorted(found) or None


KINDS = ("hostile_projectile", "enemy_aircraft", "power_up", "ground_tank", "turret",
         "clear_screen_power_up", "boss_part")
# A boss part is solid and collides, but nothing yet shows it can be destroyed, so it is
# not a target: aiming at one would be a guess dressed up as a fact.
TARGETS = ("enemy_aircraft", "ground_tank", "turret")
# Player shots travel right at exactly 11 px per game frame at the aircraft's own Y
# (420 measured steps). The vertical tolerance is estimated from two observed kills.
SHOT_SPEED = 11
# The aircraft moves 2.5 px per game frame in every direction (median of 242 measured
# decisions). Getting past something is travel, so it costs frames, not just pixels.
PLAYER_SPEED = 2.5
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


def sustained_path(position, action, frames, threats, target):
    """What holding one direction for a whole transit would cost and reach.

    A move that pays off in four steps is judged on its first step alone unless the
    path itself is measured: this walks the aircraft at its measured speed for the
    transit, against constant-velocity threats, and reports the tightest gap on the
    way and whether it ends in a firing position on the target it was flying for.
    """
    dx, dy = ACTIONS[action]
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    tightest = None
    x = y = None
    for frame in range(1, frames+1):
        x = min(max(position[0]+dx*PLAYER_SPEED*frame, xmin), xmax)
        y = min(max(position[1]+dy*PLAYER_SPEED*frame, ymin), ymax)
        for threat in threats:
            gap = ((threat["x"]+threat["vx"]*frame-x)**2 + (threat["y"]+threat["vy"]*frame-y)**2)**0.5
            tightest = gap if tightest is None else min(tightest, gap)
    if x is None:
        return None, None, None
    end_x, end_y = target["x"]+target["vx"]*frames, target["y"]+target["vy"]*frames
    reaches = end_x > x and abs(end_y-y) <= SHOT_BAND and end_x <= SHOT_MAX_X
    final_gap = round(((end_x-x)**2 + (end_y-y)**2)**0.5, 1)
    return (round(tightest, 1) if tightest is not None else None), reaches, final_gap


def where_you_have_been(recent_positions, bounds=PLAYER_BOUNDS):
    """The aircraft's own recent station-keeping, which no single decision can show.

    Runs that camped on either side of the flyable area scored worst; this reports
    where it has actually been over the sampled window, as measured positions only.
    """
    if not recent_positions or len(recent_positions) < 3:
        return None
    xmin, xmax, _, _ = bounds
    xs = sorted(p[1] for p in recent_positions)
    middle = xs[len(xs)//2]
    span = recent_positions[-1][0]-recent_positions[0][0]
    third = xmin + (xmax-xmin)/3
    two_thirds = xmin + 2*(xmax-xmin)/3
    where = ("the back third of the flyable area" if middle < third
             else "the forward third of the flyable area" if middle > two_thirds
             else "the middle of the flyable area")
    return {"frames_sampled": span, "median_x": round(middle), "mostly_in": where,
            "share_of_that_window_in_the_forward_third": round(sum(x > two_thirds for x in xs)/len(xs), 2),
            "share_of_that_window_in_the_back_third": round(sum(x < third for x in xs)/len(xs), 2)}


# Every collision recorded in this project happened at a reference gap of 9 to 22 px.
COLLISION_RANGE_PX = 22


def time_in_the_collision_range(recent_body_gaps):
    """How long the aircraft has been sitting inside the range where collisions happen.

    One decision at a time this is invisible: each says only 'inside the range'. The
    run that died had spent four consecutive decisions at 20-21 px from a tank.
    """
    samples = [(frame, gap) for frame, gap in (recent_body_gaps or []) if gap is not None]
    if not samples:
        return None
    inside = [frame for frame, gap in samples if gap <= COLLISION_RANGE_PX]
    if not inside:
        return None
    run = 0
    for _, gap in reversed(samples):
        if gap > COLLISION_RANGE_PX:
            break
        run += 1
    return {"decisions_sampled": len(samples), "decisions_inside_the_collision_range": len(inside),
            "consecutive_decisions_inside_it_now": run,
            "frames_since_the_first_of_those": samples[-1][0]-inside[0] if run else 0}


def combat_digest(obs, horizon=20, entry_edges=None, lookahead=30, recent_positions=None,
                  recent_body_gaps=None):
    tracks = {kind: [t for t in obs["tracks"] if t["kind"] == kind] for kind in KINDS}
    digest = summarize(dict(obs, tracks=tracks["hostile_projectile"]), horizon)
    # Tanks collide with the aircraft too (one observed collision), so they count as bodies.
    bodies = summarize(dict(obs, tracks=tracks["enemy_aircraft"]+tracks["ground_tank"]
                            + tracks["turret"]+tracks["boss_part"]), horizon)
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
    digest["where_you_have_been_recently"] = where_you_have_been(recent_positions)
    digest["time_in_the_collision_range"] = time_in_the_collision_range(recent_body_gaps)
    digest["field_forecast"] = field_forecast([t for t in live if t["kind"] in TARGETS],
                                              [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")])
    # The fastest speed anything is closing at right now, measured from the tracks themselves.
    approach = max((-t["vx"] for t in live if t["kind"] != "power_up" and t["vx"] is not None and t["vx"] < 0),
                   default=None)
    digest["fastest_closing_speed_px_per_frame"] = round(approach, 2) if approach else None
    for action, option in digest["actions"].items():
        option["enemy_body_anchor_gap_px"] = bodies["actions"][action]["closest_anchor_distance_px"]
        nearest = min(option["tracked_projectiles"]+bodies["actions"][action]["tracked_projectiles"],
                      key=lambda d: d["closest_anchor_distance_px"], default=None)
        option["closest_threat_direction"] = nearest["relative_direction"] if nearest else None
        option["power_up_closest_px"] = reach["actions"][action]["closest_anchor_distance_px"]
        option["clear_screen_power_up_closest_px"] = clear_reach["actions"][action]["closest_anchor_distance_px"]
        # A power-up is only worth a detour while it is still in play. Both halves of that
        # are time: the flying it takes to reach it, and the frames before it drifts out.
        for kind in ("power_up", "clear_screen_power_up"):
            gap = option[f"{kind}_closest_px"]
            option[f"frames_to_reach_{kind}"] = round(gap/PLAYER_SPEED) if gap is not None else None
            leaving = [(t["x"]+32)/-t["vx"] for t in live
                       if t["kind"] == kind and t["vx"] is not None and t["vx"] < -0.05]
            option[f"frames_until_{kind}_leaves_play"] = round(min(leaving)) if leaving else None
            option[f"holding_this_direction_closes_to_px_of_{kind}"] = None
            option[f"tightest_gap_on_the_way_to_{kind}_px"] = None
            items = [t for t in live if t["kind"] == kind]
            frames_needed = option[f"frames_to_reach_{kind}"]
            start = option["projected_position"]
            if items and start and frames_needed and frames_needed <= lookahead*3:
                nearest = min(items, key=lambda t: (t["x"]-start[0])**2 + (t["y"]-start[1])**2)
                threats = [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")]
                tight, _, final = sustained_path(start, action, frames_needed, threats, nearest)
                option[f"holding_this_direction_closes_to_px_of_{kind}"] = final
                option[f"tightest_gap_on_the_way_to_{kind}_px"] = tight
        position = option["projected_position"]
        # A squeeze is only visible if the sides are reported separately.
        sides = {"ahead": [], "behind": []}
        for t in (live if position else []):
            if t["kind"] in ("power_up", "clear_screen_power_up"):
                continue
            fx, fy = t["x"]+t["vx"]*horizon, t["y"]+t["vy"]*horizon
            sides["ahead" if fx > position[0] else "behind"].append(((fx-position[0])**2+(fy-position[1])**2)**0.5)
        (option["collision_altitudes_here"], option["lowest_safe_y_measured"],
         option["ground_object_y_here"]) = terrain_at(position, obs.get("scroll_x"), span_from=px)
        # Structures are not a floor: at one measured column a collision happened at Y 171
        # while Y 189 was flown safely. Compare against the altitudes actually recorded.
        option["terrain_hit_recorded_y"] = (min(option["collision_altitudes_here"])
                                            if option["collision_altitudes_here"] else None)
        option["shots_stopped_here_at"] = blocked_altitudes(position, obs.get("scroll_x"), span_from=px)
        option["ends_level_with_something_that_stopped_a_shot"] = bool(
            position and any(abs(position[1]-a) <= 6 for a in (option["shots_stopped_here_at"] or ())))
        # The altitude at or below which terrain is known to be solid along this path.
        # Only recorded untracked hits measure that. A tank or turret standing here measures
        # where ground targets sit, and the aircraft has flown at or below that altitude
        # without a hit in 74 of the 122 mapped columns, so it is a firing line, not a floor.
        option["terrain_floor_y"] = option["terrain_hit_recorded_y"]
        near = [a for a in (option["collision_altitudes_here"] or ())
                if position and abs(position[1]-a) <= 6]
        option["ends_where_a_collision_was_recorded"] = sorted(near) or None
        option["ends_at_or_below_terrain"] = bool(near)
        # Positive means this option ends that many pixels above the recorded collision altitude.
        option["pixels_above_recorded_terrain"] = (
            round(option["terrain_floor_y"]-position[1], 1)
            if position and option["terrain_floor_y"] is not None else None)
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
        # The gun only fires right, so a target behind is a multi-move commitment, and a
        # target drifting left at nearly the aircraft's own speed cannot be caught at all.
        # Closing rate flying back is PLAYER_SPEED + the target's vx (negative going left).
        rear = [(position[0]-(t["x"]+t["vx"]*horizon), t) for t in reachable
                if position and t["x"]+t["vx"]*horizon <= position[0]] if position else []
        # Something slipping behind is cheap to prevent and expensive to undo, so the
        # crossing is worth seeing before it happens rather than after.
        crossing = [(t["x"]-position[0])/-t["vx"] for t in reachable
                    if position and t["vx"] is not None and t["vx"] < -0.05
                    and t["x"] > position[0] and (t["x"]-position[0])/-t["vx"] <= lookahead]
        option["targets_that_will_slip_behind_you"] = len(crossing)
        option["first_slips_behind_in_frames"] = round(min(crossing)) if crossing else None
        option["frames_to_get_behind_nearest_target_behind"] = None
        option["nearest_target_behind_kind"] = None
        option["tightest_gap_if_this_direction_is_held_px"] = None
        option["holding_this_direction_reaches_a_shot_on_it"] = None
        if rear:
            gap, target = min(rear, key=lambda pair: pair[0])
            closing = PLAYER_SPEED + target["vx"]
            option["nearest_target_behind_kind"] = target["kind"]
            transit = round(gap/closing) if closing > 0.05 else None
            option["frames_to_get_behind_nearest_target_behind"] = transit
            # The transit is several moves long, so judge the whole path, not its first step.
            if transit and transit <= lookahead*2 and position:
                threats = [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")]
                (option["tightest_gap_if_this_direction_is_held_px"],
                 option["holding_this_direction_reaches_a_shot_on_it"], _) = sustained_path(
                    position, action, transit, threats, target)
        option["warning_room_px"], option["warning_room_edge"] = warning_room(position, entry_edges)
        option["retreat_room_px"] = retreat_room(position, entry_edges)
        # Pixels of room mean nothing on their own: turn both into frames.
        option["warning_time_frames"] = (round(option["warning_room_px"]/approach)
                                         if option["warning_room_px"] is not None and approach else None)
        option["retreat_time_frames"] = (round(option["retreat_room_px"]/PLAYER_SPEED)
                                         if option["retreat_room_px"] is not None else None)
        # One action can look clear for its own frames and still end where something arrives soon.
        waits = [nearest_approach(t["x"]+t["vx"]*horizon-position[0], t["y"]+t["vy"]*horizon-position[1],
                                  t["vx"], t["vy"], lookahead)[0]
                 for t in live if t["kind"] != "power_up"] if position else []
        option["threat_gap_if_you_hold_px"] = round(min(waits), 1) if waits else None
        option["targets_the_gun_would_hit"] = len(landings)
        option["soonest_hit_frames"] = landings[0][0] if landings else None
        option["soonest_hit_kind"] = landings[0][1] if landings else None
    # A constraint that forbids every option cannot be obeyed, but clearing the flags
    # deleted the warning exactly when the aircraft was already too low and told it
    # nothing (three hits at Y 174 in one run). Keep every warning; say it applies to
    # all of them, and let the clearance figure pick the way out.
    if all(o["ends_at_or_below_terrain"] for o in digest["actions"].values()):
        digest["terrain_constraint_suspended"] = (
            "every option here ends at or below the altitude where a collision was recorded, so the "
            "constraint cannot be met by any of them: the clearance figures say which climbs out fastest")
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
        if f["clear_screen_power_up_closest_px"] is None:
            clear_up = ""
        else:
            reach_cost = ("" if f["frames_to_reach_clear_screen_power_up"] is None else
                          f", about {f['frames_to_reach_clear_screen_power_up']} frames of flying away")
            if f["holding_this_direction_closes_to_px_of_clear_screen_power_up"] is not None:
                on_the_way = ("" if f["tightest_gap_on_the_way_to_clear_screen_power_up_px"] is None else
                              f" with a tightest gap of "
                              f"{f['tightest_gap_on_the_way_to_clear_screen_power_up_px']:.0f} pixels on the way")
                reach_cost += (f", and holding this direction for those frames closes to "
                               f"{f['holding_this_direction_closes_to_px_of_clear_screen_power_up']:.0f} "
                               f"pixels of it{on_the_way}")
            expiry = ("" if f["frames_until_clear_screen_power_up_leaves_play"] is None else
                      f", and it drifts out of play in about "
                      f"{f['frames_until_clear_screen_power_up_leaves_play']} frames")
            clear_up = (f"; closest approach to the screen-clearing power-up "
                        f"{f['clear_screen_power_up_closest_px']:.1f} pixels{reach_cost}{expiry} "
                        f"(touching it destroyed every live target in both observed pickups)")
        if f["power_up_closest_px"] is None:
            power_up = ""
        else:
            reach_cost = ("" if f["frames_to_reach_power_up"] is None else
                          f", about {f['frames_to_reach_power_up']} frames of flying away")
            if f["holding_this_direction_closes_to_px_of_power_up"] is not None:
                on_the_way = ("" if f["tightest_gap_on_the_way_to_power_up_px"] is None else
                              f" with a tightest gap of {f['tightest_gap_on_the_way_to_power_up_px']:.0f} "
                              f"pixels on the way")
                reach_cost += (f", and holding this direction for those frames closes to "
                               f"{f['holding_this_direction_closes_to_px_of_power_up']:.0f} pixels of it{on_the_way}")
            expiry = ("" if f["frames_until_power_up_leaves_play"] is None else
                      f", and it drifts out of play in about {f['frames_until_power_up_leaves_play']} frames")
            power_up = (f"; closest approach to the power-up {f['power_up_closest_px']:.1f} pixels{reach_cost}"
                        f"{expiry} (touching collects it; the one observed pickup happened at about 18 pixels)")
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
        slipping = ("" if not f["targets_that_will_slip_behind_you"]
                    else f" From here {f['targets_that_will_slip_behind_you']} target(s) pass behind you within "
                         f"{f['first_slips_behind_in_frames']} to 30 frames, the first in about "
                         f"{f['first_slips_behind_in_frames']} frames; the gun cannot reach them afterwards without "
                         f"flying back past them.")
        ground = ""
        if f["ends_at_or_below_terrain"]:
            hit_at = ", ".join(f"{a:.0f}" for a in f["ends_where_a_collision_was_recorded"])
            escape = ("" if f["lowest_safe_y_measured"] is None else
                      f" Altitudes flown here without a hit go down to Y {f['lowest_safe_y_measured']:.0f}, "
                      f"so this is a structure to go around or over, not a floor.")
            ground += (f" TERRAIN: this ends at Y {f['projected_position'][1]:.0f}, level with an altitude where a "
                       f"collision was actually recorded on this path (Y {hit_at}); contact is damage every "
                       f"time.{escape}")
        elif f["ends_level_with_something_that_stopped_a_shot"]:
            near = [a for a in f["shots_stopped_here_at"] if abs(f["projected_position"][1]-a) <= 6]
            ground += (" STRUCTURE: shots fired along this path have been stopped at Y "
                       + ", ".join(f"{a:.0f}" for a in near)
                       + ", which is where this option ends, so something solid is there.")
        elif f["collision_altitudes_here"]:
            ground += (" Collisions have been recorded on this path at Y "
                       + ", ".join(f"{a:.0f}" for a in f["collision_altitudes_here"])
                       + f"; this option ends {f['pixels_above_recorded_terrain']:.0f} pixels above the highest.")
        if f["ground_object_y_here"] is not None:
            ground += (f" Ground targets stand at Y {f['ground_object_y_here']:.0f} here: that is the altitude the "
                       f"gun has to be at to hit them, and it has been flown without a hit, so it is a firing "
                       f"line, not a floor.")
        if f["terrain_hit_recorded_y"] is not None:
            ground += (" A terrain collision was recorded here at Y "
                       + ", ".join(f"{a:.0f}" for a in f["collision_altitudes_here"]) + ".")
        elif f["lowest_safe_y_measured"] is not None:
            ground += f" The lowest altitude flown here without an untracked hit is Y {f['lowest_safe_y_measured']:.0f}."
        squeeze = ("" if f["gap_ahead_px"] is None and f["gap_behind_px"] is None
                   else f" Nearest threat ahead: {describe_gap(f['gap_ahead_px'])}; behind: {describe_gap(f['gap_behind_px'])}.")
        if not f["targets_behind"]:
            behind = ""
        else:
            frames = f["frames_to_get_behind_nearest_target_behind"]
            kind = (f["nearest_target_behind_kind"] or "target").replace("_", " ")
            path = ""
            if f["tightest_gap_if_this_direction_is_held_px"] is not None:
                path = (f"; holding this direction for those frames "
                        f"{'reaches a shot on it' if f['holding_this_direction_reaches_a_shot_on_it'] else 'does not line up a shot on it'}"
                        f", and the tightest gap to anything along that path is "
                        f"{f['tightest_gap_if_this_direction_is_held_px']:.0f} pixels")
            cost = (f"flying back past it takes about {frames} frames at this aircraft's measured speed"
                    if frames is not None else
                    "it is drifting away about as fast as this aircraft flies, so it cannot be caught from here")
            behind = (f" Targets behind you: {f['targets_behind']} (nearest is a {kind}, "
                      f"{f['pixels_to_pass_nearest_behind']:.0f} pixels back; {cost}{path}, and the gun can hit "
                      f"it once past).")
        if f["warning_room_px"] is None:
            room = ""
        else:
            warning = ("" if f["warning_time_frames"] is None else
                       f", about {f['warning_time_frames']} frames of warning at the fastest speed anything is "
                       f"closing at right now")
            retreat = ("" if f["retreat_time_frames"] is None else
                       f", about {f['retreat_time_frames']} frames of flying")
            room = (f" Targets ahead of you: {f['targets_ahead']}; room from the {f['warning_room_edge']} side, "
                    f"where objects have been entering: {f['warning_room_px']:.0f} pixels{warning}; room left to "
                    f"fall back away from that side: {f['retreat_room_px']:.0f} pixels{retreat}.")
        later = ("" if f["threat_gap_if_you_hold_px"] is None
                 else f" Staying there afterwards, the nearest tracked threat closes to {f['threat_gap_if_you_hold_px']:.0f} pixels.")
        lead = ""
        if f["ends_at_or_below_terrain"] or f["ends_level_with_something_that_stopped_a_shot"]:
            blocking = sorted({*(f["ends_where_a_collision_was_recorded"] or ()),
                               *[a for a in (f["shots_stopped_here_at"] or ())
                                 if abs(f["projected_position"][1]-a) <= 6]})
            evidence = ("a collision was recorded" if f["ends_at_or_below_terrain"]
                        else "our own shots have been stopped")
            clear_air = ("" if f["lowest_safe_y_measured"] is None else
                         f" Altitudes flown here without a hit reach Y {f['lowest_safe_y_measured']:.0f}.")
            lead = (f"BLOCKED: this ends at Y {f['projected_position'][1]:.0f}, level with Y "
                    + ", ".join(f"{a:.0f}" for a in blocking)
                    + f" on this path, where {evidence}. Something solid is there and contact is "
                      f"damage every time.{clear_air} ")
        if f["clear_screen_power_up_closest_px"] is not None:
            closing = ("" if f["holding_this_direction_closes_to_px_of_clear_screen_power_up"] is None else
                       f" Holding this direction for those frames closes to "
                       f"{f['holding_this_direction_closes_to_px_of_clear_screen_power_up']:.0f} pixels of it" +
                       ("." if f["tightest_gap_on_the_way_to_clear_screen_power_up_px"] is None else
                        f", with a tightest gap of "
                        f"{f['tightest_gap_on_the_way_to_clear_screen_power_up_px']:.0f} pixels on the way."))
            expiry = ("" if f["frames_until_clear_screen_power_up_leaves_play"] is None else
                      f" It drifts out of play in about {f['frames_until_clear_screen_power_up_leaves_play']} "
                      f"frames and is then gone for good.")
            lead += ("SCREEN-CLEARING POWER-UP IN PLAY - touching it destroyed every live target in both observed "
                    f"pickups. Closest approach {f['clear_screen_power_up_closest_px']:.0f} pixels, about "
                    f"{f['frames_to_reach_clear_screen_power_up']} frames of flying away.{closing}{expiry} ")
            clear_up = ""
        criteria[action] = (f"{'No directional buttons' if action == 'hold' else 'Move '+action}. {lead}{closest}"
            f"Attack: {shots}.{coming}{slipping}{squeeze}{behind}{room}{later}{ground} "
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
        # Measured from this run: where the aircraft has actually been sitting.
        "where_you_have_been_recently": digest.get("where_you_have_been_recently") or "not enough samples yet",
        # Measured from this run: how long it has been sitting where collisions happen.
        "time_in_the_collision_range": digest.get("time_in_the_collision_range")
                                       or "not inside it recently",
        "terrain": ("The ground and the platforms structures stand on are solid but are not tracked at all. Tracked tanks "
                    "and turrets sit on that terrain, so their altitude marks where it is. Every recorded collision with "
                    "terrain happened while flying at Y 174 to 191, with nothing tracked nearby. Where past runs measured "
                    "this stretch, each option says so; a column with no measurement is unknown, not safe. Only a recorded "
                    "collision measures the solid surface; a tank or turret standing somewhere marks the altitude to "
                    "shoot it from, and that altitude has been flown safely."),
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
                "live target at once. While one is in play every option leads with it: reaching it is the objective that "
                "reshapes the rest, because it pays more than any sequence of ordinary kills available in the same "
                "frames. Work the approach it offers - hold a direction long enough to close, and take the opening "
                "when the path's tightest gap allows - and give it up only when every approach crosses a threat "
                "inside the collision range. Ordinary targets will still be there afterwards; the power-up will not. A power-up that can be reached in the time it has left is worth more than an "
                "ordinary kill, because the firepower lasts for the rest of the level while a single kill does not; "
                "passing one up to keep shooting at what is already in front is the wrong trade. Power-ups drift out "
                "of play and are gone for the rest of the level: each "
                "option gives the frames of flying needed to reach one and the frames before it leaves, so a detour "
                "that fits inside the time left is a real choice, while drifting near one without closing wastes "
                "both the frames and the power-up. A target behind you cannot be shot until you get past it, and each option says how "
                "many frames that transit actually takes. A slow one, such as a tank, is worth the frames when the way "
                "is clear; one drifting away nearly as fast as this aircraft flies cannot be caught at all, and its transit "
                "cost says which. Each option also says which targets are about to pass behind you and how soon. "
                "cost says which case this is. Decide and carry it through: trading a few pixels back and forth while "
                "both sides close is how this aircraft gets boxed in with something behind it that the gun cannot "
                "reach. Sitting far forward is what creates that: everything that slips past is then a long transit "
                "away, and the room behind is the room to dodge into, measured in frames of flying. "
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
                "not take an option whose closest threat is tight. Never choose an option whose TERRAIN line says it ends at "
                "marked BLOCKED. Those lead the option because ignoring them is what has cost the most damage past the "
                "halfway point of this stage: every one of those hits happened where this map already carried "
                "evidence. A blocked band is a structure rather than a floor: "
                "at one measured column a collision happened at Y 171 while Y 189 was flown safely, so going "
                "around or under one can be as good as climbing over it, and each option says which altitudes "
                "have actually been flown there. A STRUCTURE line means our own shots were stopped at that "
                "altitude on that path: shots travel in a straight line, so something solid is there even where "
                "no collision has been recorded yet, and flying level with it invites one. Colliding with an aircraft, tank or turret is the main way this "
                "aircraft takes damage, so an option whose closest threat sits inside the collision range is a last resort. "
                "time_in_the_collision_range counts how long this has already been going on: staying inside that "
                "band decision after decision is how the run that died spent its last seconds, and no single option "
                "can show it. "
"When threats close from both sides at once, do not drift and let the gap shrink: take the option that "
                "opens the squeeze, going over or under if that is the side with room, and take the shot on the way out "
                "when one is offered. Watch the number for staying there afterwards too, because a "
                "move that is clear for its own few frames can still end where a tank, aircraft or bullet arrives moments "
                "later. An option "
                "that hits nothing, collects nothing and only keeps distance is a wasted move when a safer-or-equal option "
                "attacks. Tanks and turrets can only be hit from their own altitude, so descending to their firing line is "
                "ordinary play and not a terrain risk: the altitude a ground target stands at has been flown without a "
                "hit. Close onto that line from a horizontal distance rather than dropping onto them, since they "
                "collide like any other body. Compare the "
                "already-computed consequences, not raw coordinates. Hold is an ordinary action, not an automatic safe "
                "fallback. New objects appear from off-screen without warning; object_entries_counted_this_run says where they "
                "have come from so far in this run. where_you_have_been_recently is this aircraft's own recent "
                "station-keeping, which no single option can show: camping at either extreme of the flyable area "
                "has scored worst, one because everything that slips past is then a long transit away, the other "
                "because there is no room left to fall back into. Health and model confidence must not be used to infer safety.")}}}
