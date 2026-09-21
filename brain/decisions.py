"""Experimental categorical Jev interface; legacy combat_request remains the baseline.

All geometry and comparisons use combat_digest's measured facts. Confidence gates
preference changes, never certifies safety. Each fallback is explicit in the log.
"""
import math

from brain.digest import ACTIONS

POLICY = "categorical-v1"
import os

# Below this, the policy plays a computed move instead of Jev's answer. Measured over three
# matched runs, the floor of 0.5 overrode 31% of decisions, every one of them for low
# confidence rather than a measured constraint, and those runs scored 71% of units against
# 78% for the legacy policy acting on median confidence 0.27. The floor is the thing under
# test, so it is settable per run rather than baked in.
CONFIDENCE_FLOOR = float(os.getenv("JEV_CONFIDENCE_FLOOR", "0.5"))
COLLISION_BAND = 22     # Upper end of the observed reference-gap collision range.


def gap(option):
    values = [option.get(name) for name in ("closest_anchor_distance_px", "enemy_body_anchor_gap_px")]
    return min((value for value in values if value is not None), default=None)


def blocked(option):
    return bool(option.get("ends_at_or_below_terrain") or
                option.get("ends_level_with_something_that_stopped_a_shot"))


def endpoint_gap(option):
    return min((option[name] for name in ("gap_ahead_px", "gap_behind_px")
                if option.get(name) is not None), default=float("inf"))


def comparison(value, reference, lower=True):
    if value is None or reference is None:
        return "unknown"
    if abs(value-reference) < 0.1:
        return "unchanged"
    return "improves" if (value < reference) == lower else "worsens"


def pickup_viable(option, kind):
    distance = option.get(f"{kind}_closest_px")
    arrival = option.get(f"frames_to_reach_{kind}")
    expiry = option.get(f"frames_until_{kind}_leaves_play")
    path_gap = option.get(f"tightest_gap_on_the_way_to_{kind}_px")
    return (distance is not None and arrival is not None
            and (expiry is None or arrival <= expiry)
            and (path_gap is None or path_gap > COLLISION_BAND))


def attack_rank(option):
    hits = option.get("targets_the_gun_would_hit", 0)
    kind = option.get("soonest_hit_kind")
    aim = option.get("aim_error_px")
    rear = option.get("frames_to_get_past_it_and_onto_its_line")
    return (bool(hits), kind == "turret" if hits else False, hits,
            option.get("targets_entering_your_line_soon", 0),
            -aim if aim is not None else -10000,
            -rear if rear is not None else -10000)


def pickup_rank(option):
    for priority, kind in ((2, "clear_screen_power_up"), (1, "power_up")):
        if pickup_viable(option, kind):
            return priority, -option[f"{kind}_closest_px"]
    return 0, -10000


def position_rank(option, boss):
    if boss:
        x, y = option["projected_position"]
        # Carl's demonstrated strategy: stay in the bottom left, off the hull.
        return -(x-16 + 191-y), min(endpoint_gap(option), 60)
    retreat = option.get("retreat_time_frames") or 0
    warning = option.get("warning_time_frames") or 0
    return (min(retreat, warning), min(endpoint_gap(option), 60))


def selection_plan(digest):
    options = digest["actions"]
    hold_position = options["hold"]["projected_position"]
    moving = [action for action in ACTIONS if action == "hold" or
              options[action]["projected_position"] != hold_position]
    unblocked = [action for action in moving if not blocked(options[action])]
    clear = [action for action in unblocked if gap(options[action]) is None or
             gap(options[action]) > COLLISION_BAND]
    escaping = not clear
    if clear:
        eligible = clear
    else:
        # A path includes its starting point: when already in a collision band,
        # every path can have the same minimum. Use endpoint clearance to escape.
        candidates = unblocked or moving
        escape_ranks = {action: (
            (options[action].get("distance_to_nearest_blocked_altitude_px") or 0) if not unblocked else 0,
            endpoint_gap(options[action])) for action in candidates}
        best = max(escape_ranks.values())
        eligible = [action for action in candidates if escape_ranks[action] == best]
    boss = bool(digest.get("boss_body"))
    has_pickup = any(pickup_rank(options[action])[0] for action in eligible)
    has_target = any(options[action].get("aim_error_px") is not None or
                     options[action].get("targets_the_gun_would_hit", 0) or
                     options[action].get("targets_behind", 0) for action in eligible)
    objective = "position" if escaping else "pickup" if has_pickup else "position" if boss else "attack" if has_target else "position"
    rank = {"attack": attack_rank, "pickup": pickup_rank,
            "position": lambda option: position_rank(option, boss)}[objective]
    ranks = {action: rank(options[action]) for action in eligible}
    best = max(ranks.values())
    fallback = [action for action in eligible if ranks[action] == best]
    previous = (digest.get("what_you_have_been_doing") or {}).get("last_choices_oldest_first") or []
    return {"objective": objective, "admissible_moves": eligible,
            "fallback_moves": fallback, "previous_move": previous[-1] if previous else None,
            "escape_required": escaping}


def categorical_request(digest, model="jev-latest"):
    options, hold = digest["actions"], digest["actions"]["hold"]
    plan = selection_plan(digest)
    attack, pickup, position = {}, {}, {}
    best_attack = max(attack_rank(option) for option in options.values())
    for action, option in options.items():
        common = {"what": "stay still" if action == "hold" else f"move {action}",
                  "admissible": action in plan["admissible_moves"]}
        attack[action] = dict(common,
            gun="hits "+option["soonest_hit_kind"].replace("_", " ") if option.get("targets_the_gun_would_hit") else "no hit lined up",
            alignment=comparison(option.get("aim_error_px"), hold.get("aim_error_px")),
            future_shots="targets enter this firing line" if option.get("targets_entering_your_line_soon") else "none predicted",
            rear_approach=comparison(option.get("frames_to_get_past_it_and_onto_its_line"), hold.get("frames_to_get_past_it_and_onto_its_line")),
            computed_attack_comparison="best" if attack_rank(option) == best_attack else "other",
            structure="blocks some targets" if option.get("targets_hidden_behind_structure") else "no measured obstruction")
        pickup[action] = dict(common)
        for label, kind in (("screen_clear", "clear_screen_power_up"), ("weapon_upgrade", "power_up")):
            distance = option.get(f"{kind}_closest_px")
            pickup[action][label] = ("none tracked" if distance is None else
                "arrival or path fails measured constraints" if not pickup_viable(option, kind) else
                comparison(distance, hold.get(f"{kind}_closest_px"))+" approach; estimated arrival fits expiry")
        lane = option.get("lane_west_through_what_is_coming")
        current_lane = hold.get("lane_west_through_what_is_coming")
        position[action] = dict(common,
            room=option.get("room_description"),
            retreat_room=comparison(option.get("retreat_time_frames"), hold.get("retreat_time_frames"), lower=False),
            west_passage=comparison(lane.get("how_far_you_are_from_it_px") if lane and lane["width_px"] >= 32 else None,
                                    current_lane.get("how_far_you_are_from_it_px") if current_lane else None),
            threats_after_move="inside observed collision range" if endpoint_gap(option) <= COLLISION_BAND else "outside observed collision range")
        if digest.get("boss_body"):
            position[action]["bottom_left_pocket"] = comparison(
                -position_rank(option, True)[0], -position_rank(hold, True)[0])
    state = {"selection": plan,
        "coverage": "Measured short forecasts; untracked terrain and threats remain unknown. Admissible is not guaranteed safe.",
        "known_tracks": {"aircraft":digest["enemy_count"], "bullets":digest["projectile_count"],
                         "power_ups":digest["power_up_count"], "tanks":digest["tank_count"],
                         "turrets":digest["turret_count"], "screen_clearing_power_ups":digest["clear_screen_power_up_count"]}}
    if digest.get("boss_body"):
        state["boss_tactic_from_Carl"] = "Hold the bottom left under the invincible straight missiles. Leave when the hull crowds you; return when clear. Small turning missiles can be shot."
    return {"model":model, "state":state, "questions":{
        "attack":{"type":"choice", "instructions":"If attacking, which admissible move best establishes a firing line? Turrets drop upgrades. Use the computed comparisons; keep an effective line or continue improving it.", "criteria":attack},
        "pickup":{"type":"choice", "instructions":"If collecting a power-up, which admissible move best advances the approach before it expires? Prefer the screen-clear item, then a weapon upgrade. Continue an effective approach.", "criteria":pickup},
        "position":{"type":"choice", "instructions":"If repositioning, which admissible move best preserves maneuvering room? Use Carl's boss tactic when present; otherwise favor a passage past approaching enemies with room to retreat.", "criteria":position}}}


def validate_choices(answer, questions):
    answers = answer.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("Missing or unexpected policy answers")
    checked = {}
    for name, question in questions.items():
        result = answers[name]
        options = set(question["criteria"])
        if not isinstance(result, dict) or result.get("type", "choice") != "choice":
            raise ValueError("Invalid answer type")
        confidence, probabilities = result.get("confidence"), result.get("probabilities")
        if (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1
                or not isinstance(probabilities, dict) or set(probabilities) != options
                or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
                or abs(sum(probabilities.values())-1) > 0.01 or result.get("choice") not in options):
            raise ValueError("Invalid policy Choice distribution")
        checked[name] = {"choice":result["choice"], "confidence":confidence, "probabilities":probabilities}
    return checked


def compose(body, answers):
    plan = body["state"]["selection"]
    selected = answers[plan["objective"]]
    chosen = selected["choice"]
    source, reason = "jev", "confident_admissible_choice"
    floor = float(os.getenv("JEV_CONFIDENCE_FLOOR", CONFIDENCE_FLOOR))
    if chosen not in plan["admissible_moves"] or selected["confidence"] < floor:
        reason = "measured_constraint" if chosen not in plan["admissible_moves"] else "low_confidence"
        candidates = plan["fallback_moves"]
        previous = plan["previous_move"]
        chosen = previous if previous in candidates else "hold" if "hold" in candidates else candidates[0]
        source = "jev_fallback"
        reason += "_continue" if chosen == previous else "_computed_move"
    return {"choice":chosen, "raw_choice":selected["choice"],
            "confidence":selected["confidence"], "probabilities":selected["probabilities"],
            "answers":answers, "objective":plan["objective"], "decision_source":source,
            "selection_reason":reason, "policy":POLICY}
