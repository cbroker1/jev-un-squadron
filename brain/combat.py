"""Limited experimental combat summaries. Reference gaps are not collision clearance."""
import json
from pathlib import Path

from .digest import ACTIONS, PLAYER_BOUNDS, direction_words, nearest_approach, summarize

TERRAIN_MAP = Path(__file__).resolve().parent.parent / "terrain_map.json"
DANGER_MAP = Path(__file__).resolve().parent.parent / "danger_map.json"
BOSS_COLUMN_BASE = 100000   # matches build_danger_map.py: the boss is keyed by screen position
_danger = None
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


def danger_cells():
    """Measured record of what happened to past runs at each position and altitude."""
    global _danger
    if _danger is None:
        try:
            data = json.loads(DANGER_MAP.read_text())
            _danger = (data["cells"], data["column_px"], data["altitude_px"],
                       data["doomed_window_frames"], data.get("hurt_window_frames", 30))
        except (OSError, ValueError, KeyError):
            _danger = ({}, 8, 8, 60, 30)
    return _danger


def danger_at(position, scroll):
    """How past runs fared at this exact position: frames flown, and deaths soon after.

    Every frame of every run is evidence, so this covers structures, emplacements and
    crossfire alike. A cell nobody has flown enough is unknown, not safe.
    """
    cells, column_px, altitude_px, window, hurt_window = danger_cells()
    if not cells or scroll is None or not position:
        return None
    # At the boss the scroll counter wraps; screen position is the stable key there.
    column = (BOSS_COLUMN_BASE + int(position[0])//column_px if scroll > 60000
              else int((position[0]+scroll)//column_px))
    key = f"{column},{int(position[1]//altitude_px)}"
    cell = cells.get(key)
    if not cell:
        return None
    return {"frames_flown_here_in_past_runs": cell["frames"],
            "how_many_were_within_a_second_of_being_destroyed": cell["deaths_soon_after"],
            "how_many_were_just_before_taking_a_hit": cell.get("hits_soon_after", 0),
            "window_frames": window, "hit_window_frames": hurt_window}


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
# Carl, who plays this game: every part of the boss is vulnerable, and a part that
# flashes when shot is taking damage. So boss parts are targets as well as bodies.
TARGETS = ("enemy_aircraft", "ground_tank", "turret", "boss_part")
# Player shots travel right at exactly 11 px per game frame at the aircraft's own Y
# (420 measured steps). The vertical tolerance is estimated from two observed kills.
SHOT_SPEED = 11
# The aircraft moves 2.5 px per game frame in every direction (median of 242 measured
# decisions). Getting past something is travel, so it costs frames, not just pixels.
PLAYER_SPEED = 2.5
# Structure evidence is recorded and cleared over this band; see build_terrain_map.py.
STRUCTURE_BAND = 6
SHOT_BAND = 10          # the widest band any kind uses; kept for callers that ask generally
# Measured as the share of frames at each offset that were followed by a kill within 20
# frames, over 24 runs. Offset is aircraft altitude minus target altitude, so positive
# means flying below the target's reference point.
#
#   ground targets:  -8..-7  5.8%   -4..-3  32%   -2..-1  68%   2..3  74%   6..7  96%
#   aircraft:        -8..-7   84%    0..1    96%   8..9    89%  16..17  79%  20..21 52%
#
# Ground targets are only reliably hit from level with them or below; an earlier symmetric
# 10 px band claimed hits from 8 px above, where the real rate is 5.8%, and one run held
# that altitude for forty decisions while every shot sailed over the tanks.
# Carl, from playing it: a ground target is always reachable, you just drop a little.
# The measured kill rate by offset backs a wider band than the -3 I first set: -6..-5 is
# 40%, -4..-3 is 32%, -2..-1 is 68%. So a tank at Y 196 is hit from Y 190, which is inside
# the flyable range; claiming it could not be shot at all was wrong.
FIRING_BANDS = {"ground_tank": (-6, 10), "turret": (-6, 10), "enemy_aircraft": (-8, 17)}
DEFAULT_BAND = (-8, 17)


def on_the_gun_line(shooter_y, target_y, kind):
    """Is a shot fired at this altitude on the line that has actually killed this kind?"""
    low, high = FIRING_BANDS.get(kind, DEFAULT_BAND)
    return low <= shooter_y-target_y <= high
SHOT_MAX_X = 251


def shot_is_blocked(position, reach_x, scroll, spread=1):
    """Does a structure stand between this position and where the shot would land?

    Shots travel right along the aircraft's own Y, so the columns between it and the
    target are exactly the ones the shot-stop map already measured: if one of them has
    stopped a shot at this altitude, this one stops too.
    """
    columns, bucket = terrain_columns()
    if not columns or scroll is None or scroll > 60000 or not position:
        return False
    px, py = position
    start, end = sorted((int((px+scroll)//bucket), int((reach_x+scroll)//bucket)))
    for column in range(start, end+1):
        entry = columns.get(column)
        if not entry:
            continue
        for altitude in (entry.get("shots_stopped_at") or ()):
            # The same band the map clears over, so evidence and rule agree.
            if abs(altitude-py) <= STRUCTURE_BAND and column > start+spread:
                return True          # measured solid on the way, past the muzzle
    return False


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
            if on_the_gun_line(py, target["y"] + target["vy"]*frame, target["kind"])                     and (x-px)/SHOT_SPEED <= window:
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
        if meet_x > SHOT_MAX_X or not on_the_gun_line(py, target["y"] + target["vy"]*travel, target["kind"]):
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


def field_forecast(targets, threats, window=30, scroll=None):
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
            cell = {"xy": [x, y], "targets_into_line": coming,
                    "first_in_frames": soonest, "nearest_threat_px": round(min(gaps), 1) if gaps else None}
            record = danger_at([x, y], scroll)
            if record and record["frames_flown_here_in_past_runs"]:
                cell["past_runs_died_within_a_second_of_here"] =                     record["how_many_were_within_a_second_of_being_destroyed"]
                cell["past_runs_were_hit_soon_after_here"] = record["how_many_were_just_before_taking_a_hit"]
                cell["frames_past_runs_spent_here"] = record["frames_flown_here_in_past_runs"]
            cells.append(cell)
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
    reaches = end_x > x and on_the_gun_line(y, end_y, target["kind"]) and end_x <= SHOT_MAX_X
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


def clear_targets(position, targets, scroll, found=None):
    """The targets this position can actually shoot, with structures in the way removed.

    Uses the map built from past runs and, just as importantly, the walls this run has
    already discovered: a third of the shots fired along a ground target's line in one run
    stopped short of it, and a wall does not move once found.
    """
    return [t for t in targets
            if not shot_is_blocked(position, t["x"], scroll)
            and not found_blocked(position, t["x"], scroll, found)]


def found_blocked(position, reach_x, scroll, found, band=6, skip=2, need=2):
    """Is a wall this run already found standing between the aircraft and that point?

    A single stop can be an enemy this code cannot classify being hit without dying, and a
    false wall kept for the whole run suppresses good firing lines: the opening segment
    dropped from 17.3 kills to 15.7 when one stop was enough. Two stops in the same place
    are required, which a real wall produces within a second at six shots a second.
    """
    if not found or scroll is None or not position:
        return False
    base = 100000 if scroll > 60000 else 0
    here = int(position[0])//4 + base if scroll > 60000 else int((position[0]+scroll)//4)
    there = int(reach_x)//4 + base if scroll > 60000 else int((reach_x+scroll)//4)
    low, high = sorted((here, there))
    for column in range(low+skip, high+1):
        for (col, y), seen in found.items():
            if col == column and abs(y-position[1]) <= band and seen >= need:
                return True
    return False


OPPOSITES = {"left": "right", "right": "left", "up": "down", "down": "up"}


def what_you_have_been_doing(recent_choices):
    """The aircraft's own recent choices, which nothing else in the request carries.

    Every decision is judged fresh, so a commitment that takes several moves - flying back
    past a target, crossing to a power-up - cannot be sustained: the next request has no
    memory of having started one. Measured, not advised: this reports the choices and how
    often they reversed, and says nothing about what to do next.
    """
    if not recent_choices:
        return None
    recent = list(recent_choices)[-8:]
    reversals = sum(1 for a, b in zip(recent, recent[1:]) if OPPOSITES.get(a) == b)
    held = 1
    for earlier in reversed(recent[:-1]):
        if earlier != recent[-1]:
            break
        held += 1
    return {"last_choices_oldest_first": recent,
            "decisions_spent_going_the_same_way": held,
            "times_you_reversed_in_those": reversals}


def wall_in_front_of_you(recent_shot_stops, py, band=10, need=2):
    """Where our own shots have just been stopping at this altitude, if they have.

    The map only knows columns some past run probed. This is the same evidence gathered
    live: shots travel right at a measured 11 px per frame, so several stopping at the
    same place with nothing dying there means something solid is in front of the aircraft
    right now, whatever the map knows. A run once spent forty-five decisions firing into
    a structure that was not in the map while killable targets sat on screen.
    """
    at_this_altitude = [x for _, x, y in (recent_shot_stops or []) if abs(y-py) <= band]
    if len(at_this_altitude) < need:
        return None
    return {"shots_stopped_recently": len(at_this_altitude),
            "nearest_stop_x": min(at_this_altitude),
            "reading": "shots from this altitude are being stopped before they reach that far"}


def combat_digest(obs, horizon=20, entry_edges=None, lookahead=30, recent_positions=None,
                  recent_body_gaps=None, recent_choices=None, recent_shot_stops=None,
                  walls_found_this_run=None):
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
    digest["what_you_have_been_doing"] = what_you_have_been_doing(recent_choices)
    digest["quietest_altitude_right_now"] = quietest_altitude(
        [obs["player"]["x"], obs["player"]["y"]],
        [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")])
    digest["field_forecast"] = field_forecast([t for t in live if t["kind"] in TARGETS],
                                              [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")],
                                              scroll=obs.get("scroll_x"))
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
        option["measured_danger_here"] = danger_at(position, obs.get("scroll_x"))
        # A warning that fires on every option is no warning at all, so always carry the
        # gradient with it: how far this option ends from the nearest solid altitude.
        solid = sorted({*(option["collision_altitudes_here"] or ()),
                        *(option["shots_stopped_here_at"] or ())})
        option["distance_to_nearest_blocked_altitude_px"] = (
            round(min(abs(position[1]-a) for a in solid), 1) if solid and position else None)
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
        # A shot cannot pass through a structure, so a target behind one is not reachable.
        all_targets = [t for t in live if t["kind"] in TARGETS]
        reachable = (clear_targets(position, all_targets, obs.get("scroll_x"), walls_found_this_run)
                     if position else all_targets)
        # Live evidence beats the map: if shots from this altitude are stopping short,
        # nothing beyond that point can be hit from here, whatever the map knows.
        wall = wall_in_front_of_you(recent_shot_stops, position[1]) if position else None
        option["shots_stopping_short_here"] = wall
        option["lane_west_through_what_is_coming"] = lane_going_back(
            position, [t for t in live if t["kind"] not in ("power_up", "clear_screen_power_up")])
        # The gun fires along the aircraft's own line, so a ground target is only hittable
        # from the altitudes that have actually killed its kind. The flyable floor is 191,
        # so a tank sitting at 196 needs an altitude that cannot be flown: runs have spent
        # a hundred decisions shooting over one without being told the altitude needed.
        option["altitude_that_hits_the_nearest_ground_target"] = None
        option["pixels_too_high_for_it"] = None
        ground_ahead = [t for t in reachable
                        if t["kind"] in ("ground_tank", "turret") and position and t["x"] > position[0]]
        if ground_ahead:
            nearest_ground = min(ground_ahead, key=lambda t: t["x"]-position[0])
            low, high = FIRING_BANDS.get(nearest_ground["kind"], DEFAULT_BAND)
            window = (round(nearest_ground["y"]+low), round(nearest_ground["y"]+high))
            option["altitude_that_hits_the_nearest_ground_target"] = list(window)
            option["pixels_too_high_for_it"] = max(0, round(window[0]-position[1]))
        if wall:
            reachable = [t for t in reachable if t["x"] < wall["nearest_stop_x"]]
        option["targets_hidden_behind_structure"] = len(all_targets)-len(reachable)
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
        # A run destroys about 40% of the units it meets; the rest leave alive. A target
        # drifting off the left edge that never crosses the gun line is a kill being lost,
        # and it has a clock, the same way a power-up does.
        leaving = []
        for target in (reachable if position else []):
            if target["vx"] is None or target["vx"] >= -0.05:
                continue
            frames_left = (target["x"]+32)/-target["vx"]
            if frames_left > lookahead*3:
                continue
            crosses = any(on_the_gun_line(position[1], target["y"]+target["vy"]*f, target["kind"])
                          and target["x"]+target["vx"]*f > position[0]
                          for f in range(0, int(frames_left)+1, 3))
            if not crosses:
                leaving.append(frames_left)
        option["targets_leaving_unshot"] = len(leaving)
        option["soonest_one_leaves_in_frames"] = round(min(leaving)) if leaving else None
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
            # Getting past something is only half the manoeuvre: the gun fires along the
            # aircraft's own line, so it must also be at the target's firing altitude.
            # Judging a pure sideways hold said 'this does not line up a shot' at every
            # decision, even with the tank 0.2 px away, because flying back never changes
            # altitude. The move is back, then down.
            low, high = FIRING_BANDS.get(target["kind"], DEFAULT_BAND)
            window = (target["y"]+low, target["y"]+high)
            drop = 0 if window[0] <= position[1] <= window[1] else min(
                abs(position[1]-window[0]), abs(position[1]-window[1]))
            option["frames_to_drop_onto_its_line"] = round(drop/PLAYER_SPEED)
            option["frames_to_get_past_it_and_onto_its_line"] = (
                transit + round(drop/PLAYER_SPEED) if transit is not None else None)
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
    blocked_now = [a for a, o in digest["actions"].items()
                   if o["ends_at_or_below_terrain"] or o["ends_level_with_something_that_stopped_a_shot"]]
    if len(blocked_now) == len(digest["actions"]):
        clearances = {a: o["distance_to_nearest_blocked_altitude_px"] or 0
                      for a, o in digest["actions"].items()}
        best = max(clearances, key=clearances.get)
        digest["every_option_is_blocked"] = (
            f"every option here ends level with something solid; the most clearance is '{best}' at "
            f"{clearances[best]:.0f} px, and climbing or dropping clear of the band is the way out")
    if all(o["ends_at_or_below_terrain"] for o in digest["actions"].values()):
        digest["terrain_constraint_suspended"] = (
            "every option here ends at or below the altitude where a collision was recorded, so the "
            "constraint cannot be met by any of them: the clearance figures say which climbs out fastest")
    return digest


def lane_going_back(position, threats, look_ahead_px=120, clearance=24):
    """The widest altitude a run could pass through to get west of what is coming at it.

    Threats arriving from ahead occupy bands of altitude; between them there is usually a
    gap wide enough to fly through and end up behind them. This reports the middle of the
    widest such gap and how wide it is, measured, with no claim that taking it is right.
    """
    if not position:
        return None
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    ahead = [t for t in threats if position[0] < t["x"] <= position[0]+look_ahead_px]
    if not ahead:
        return None
    blocked = sorted((t["y"]-clearance, t["y"]+clearance) for t in ahead)
    free, edge = [], ymin
    for low, high in blocked:
        if low > edge:
            free.append((edge, low))
        edge = max(edge, high)
    if edge < ymax:
        free.append((edge, ymax))
    if not free:
        return None
    low, high = max(free, key=lambda span: span[1]-span[0])
    return {"altitude": round((low+high)/2), "width_px": round(high-low),
            "how_far_you_are_from_it_px": round(abs((low+high)/2 - position[1]))}


def quietest_altitude(position, threats, window=30, step=8):
    """The altitude whose next few seconds are clearest of everything tracked.

    Measured across the flyable range against constant-velocity paths. At the boss the fire
    sits between Y 120 and 144 in about a thousand frames per band and is almost absent
    above Y 112, while attempts kept dying at Y 176 to 183; nothing in the request said
    where the quiet air was.
    """
    if not position:
        return None
    xmin, xmax, ymin, ymax = PLAYER_BOUNDS
    best = None
    for altitude in range(int(ymin), int(ymax)+1, step):
        clearance = None
        for threat in threats:
            gap = nearest_approach(threat["x"]-position[0], threat["y"]-altitude,
                                   threat["vx"], threat["vy"], window)[0]
            clearance = gap if clearance is None else min(clearance, gap)
        if clearance is None:
            continue
        if best is None or clearance > best[0]:
            best = (clearance, altitude)
    if not best:
        return None
    clearance, altitude = best
    return {"altitude": altitude, "clearance_px": round(clearance, 1),
            "frames_to_reach_it": round(abs(altitude-position[1])/PLAYER_SPEED)}


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
        lane = f.get("lane_west_through_what_is_coming")
        lane_text = ("" if not lane or lane["width_px"] < 32 else
                     f" The widest gap through what is coming at you is {lane['width_px']} pixels of altitude "
                     f"centred on Y {lane['altitude']}, {lane['how_far_you_are_from_it_px']} pixels from this "
                     f"option's line; passing through it ends up west of them.")
        stopping = ("" if not f.get("shots_stopping_short_here") else
                    f" Your own shots from this altitude have stopped short "
                    f"{f['shots_stopping_short_here']['shots_stopped_recently']} times in the last two seconds, "
                    f"the nearest at x {f['shots_stopping_short_here']['nearest_stop_x']}, so something solid is "
                    f"there now and nothing beyond it can be hit from this line.")
        hidden = ("" if not f.get("targets_hidden_behind_structure") else
                  f" {f['targets_hidden_behind_structure']} target(s) sit behind a structure from here, where "
                  f"shots have been stopped before, so the gun cannot reach them from this altitude.")
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
        needed = ""
        if f["altitude_that_hits_the_nearest_ground_target"]:
            low, high = f["altitude_that_hits_the_nearest_ground_target"]
            short = f["pixels_too_high_for_it"]
            needed = (f" The nearest ground target ahead is hit from Y {low} to {high}"
                      + (f", and this option ends {short} pixels above that: dropping that far lines it up."
                         if short else ", and this option ends inside that."))
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
        losing = ("" if not f["targets_leaving_unshot"]
                  else f" {f['targets_leaving_unshot']} tracked target(s) will drift out of play without ever "
                       f"crossing the gun's line from here, the first in about "
                       f"{f['soonest_one_leaves_in_frames']} frames.")
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
                path = (f", with a tightest gap of {f['tightest_gap_if_this_direction_is_held_px']:.0f} "
                        f"pixels to anything along the way")
            whole = ""
            if f.get("frames_to_get_past_it_and_onto_its_line") is not None:
                drop = f["frames_to_drop_onto_its_line"]
                whole = (f"; getting past it and onto its firing line takes about "
                         f"{f['frames_to_get_past_it_and_onto_its_line']} frames in total"
                         + (f", of which {drop} are the drop onto its altitude" if drop else
                            ", and this option is already at its altitude"))
            cost = (f"flying back past it takes about {frames} frames at this aircraft's measured speed"
                    if frames is not None else
                    "it is drifting away about as fast as this aircraft flies, so it cannot be caught from here")
            behind = (f" Targets behind you: {f['targets_behind']} (nearest is a {kind}, "
                      f"{f['pixels_to_pass_nearest_behind']:.0f} pixels back; {cost}{path}{whole}).")
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
        danger = ""
        if f["measured_danger_here"]:
            record = f["measured_danger_here"]
            deaths = record["how_many_were_within_a_second_of_being_destroyed"]
            hits = record.get("how_many_were_just_before_taking_a_hit", 0)
            danger = (f" Past runs flew {record['frames_flown_here_in_past_runs']} frames at this exact "
                      f"position and altitude; {deaths} of those frames came within "
                      f"{record['window_frames']} frames of the aircraft being destroyed, and {hits} "
                      f"came within {record['hit_window_frames']} frames of it taking a hit.")
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
            gap = f["distance_to_nearest_blocked_altitude_px"]
            lead = (f"BLOCKED ({gap:.0f} px clear): this ends at Y {f['projected_position'][1]:.0f}, level with Y "
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
            f"Attack: {shots}.{stopping}{hidden}{needed}{coming}{losing}{slipping}{lane_text}{squeeze}{behind}{room}{later}{danger}{ground} "
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
        "every_option_is_blocked": digest.get("every_option_is_blocked") or "no",
        "field_forecast_next_30_frames": digest.get("field_forecast"),
        # Measured from this run: where the aircraft has actually been sitting.
        "where_you_have_been_recently": digest.get("where_you_have_been_recently") or "not enough samples yet",
        # Measured from this run: how long it has been sitting where collisions happen.
        "time_in_the_collision_range": digest.get("time_in_the_collision_range")
                                       or "not inside it recently",
        # Measured from this run: the aircraft's own recent choices. Nothing else in the
        # request carries them, so a multi-move commitment cannot otherwise be sustained.
        "what_you_have_been_doing": digest.get("what_you_have_been_doing") or "no choices yet",
        # Measured now: which altitude's next second is clearest of everything tracked.
        "quietest_altitude_right_now": digest.get("quietest_altitude_right_now") or "nothing tracked",
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
                "Carl, who plays this game well, gives the way out of a squeeze: move to the middle of the screen "
                "and then keep backing up, so the units coming at you pass above and below instead of closing on "
                "you. The stage is built for that. Sitting still low or forward while they arrive is what turns "
                "into a squeeze, and every run that has been squeezed took damage in it. "
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
                "have come from so far in this run. what_you_have_been_doing is the aircraft's own last few choices. "
                "Each option also carries what actually happened to past runs at that "
                "exact position and altitude, counted from every frame ever flown there; a position no run has "
                "flown enough is unknown rather than safe. where_you_have_been_recently is this aircraft's own recent "
                "station-keeping, which no single option can show: camping at either extreme of the flyable area "
                "has scored worst, one because everything that slips past is then a long transit away, the other "
                "because there is no room left to fall back into. Health and model confidence must not be used to infer safety.")}}}
