"""Contract, uncertainty, collision escape, and bridge tests for the opt-in policy."""
import sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # the code under test lives in src/
import io
import json
import unittest
from unittest.mock import patch

from brain.combat import combat_digest, combat_request
from brain.decisions import POLICY, categorical_request, compose, selection_plan, validate_choices
from brain.digest import ACTIONS
import play_segment
import test_combat


def digest():
    return combat_digest({"source_frame":101,"player":{"x":96,"y":112},"tracks":[]}, horizon=3)


def answers(body, choice="up", confidence=0.8):
    return {name:{"choice":choice,"confidence":confidence,
                  "probabilities":{action:0.84 if action == choice else 0.04 for action in ACTIONS}}
            for name in body["questions"]}


class DecisionTests(unittest.TestCase):
    def test_compact_request_reduces_bytes_and_separates_questions(self):
        state = digest()
        body = categorical_request(state)
        self.assertEqual(set(body["questions"]), {"attack","pickup","position"})
        self.assertLess(len(json.dumps(body)), len(json.dumps(combat_request(state)))*0.7)
        for question in body["questions"].values():
            for option in question["criteria"].values():
                self.assertTrue(all(type(value) not in (int,float) for value in option.values()))

    def test_initial_collision_distance_does_not_hide_escape_gradient(self):
        state = digest()
        for action, option in state["actions"].items():
            option.update(closest_anchor_distance_px=10, gap_ahead_px=40 if action == "up" else 10)
        plan = selection_plan(state)
        self.assertTrue(plan["escape_required"])
        self.assertEqual(plan["admissible_moves"], ["up"])

    def test_confidence_cannot_override_measured_collision(self):
        state = digest()
        state["actions"]["up"]["ends_at_or_below_terrain"] = True
        body = categorical_request(state)
        result = compose(body, answers(body, "up", 1.0))
        self.assertNotEqual(result["choice"], "up")
        self.assertEqual(result["raw_choice"], "up")
        self.assertEqual(result["decision_source"], "jev_fallback")
        self.assertTrue(result["selection_reason"].startswith("measured_constraint"))

    def test_low_confidence_repeats_only_a_currently_eligible_good_move(self):
        state = digest()
        state["what_you_have_been_doing"] = {"last_choices_oldest_first":["left"]}
        for option in state["actions"].values():
            option.update(retreat_time_frames=10, warning_time_frames=10)
        body = categorical_request(state)
        result = compose(body, answers(body, "right", 0.2))
        self.assertEqual(result["choice"], "left")
        state["actions"]["left"]["closest_anchor_distance_px"] = 12
        body = categorical_request(state)
        result = compose(body, answers(body, "left", 0.2))
        self.assertNotEqual(result["choice"], "left")

    def test_expired_pickup_is_not_a_collection_objective(self):
        state = digest()
        for option in state["actions"].values():
            option.update(power_up_closest_px=100, frames_to_reach_power_up=40,
                          frames_until_power_up_leaves_play=20)
        self.assertNotEqual(selection_plan(state)["objective"], "pickup")
        state["actions"]["up"].update(frames_to_reach_power_up=5)
        self.assertEqual(selection_plan(state)["objective"], "pickup")

    def test_movement_into_a_bound_is_not_a_new_action(self):
        state = digest()
        state["actions"]["left"]["projected_position"] = state["actions"]["hold"]["projected_position"]
        self.assertNotIn("left", selection_plan(state)["admissible_moves"])

    def test_validator_rejects_missing_and_malformed_answers(self):
        body = categorical_request(digest())
        good = answers(body)
        self.assertEqual(set(validate_choices({"answers":good}, body["questions"])), set(good))
        with self.assertRaises(ValueError):
            validate_choices({"answers":{"attack":good["attack"]}}, body["questions"])
        for bad in (float("nan"), True, -0.1, 1.1):
            changed = answers(body)
            changed["position"]["confidence"] = bad
            with self.assertRaises(ValueError):
                validate_choices({"answers":changed}, body["questions"])
        changed = answers(body)
        changed["pickup"]["probabilities"].pop("hold")
        with self.assertRaises(ValueError):
            validate_choices({"answers":changed}, body["questions"])

    def test_one_http_request_carries_all_questions_and_retains_answers(self):
        body = categorical_request(digest())
        reply = io.BytesIO(json.dumps({"answers":answers(body)}).encode())
        with patch.object(play_segment.urllib.request, "urlopen", return_value=reply) as http:
            result, _ = play_segment.decide(body, "live", 1, "unit-test-placeholder")
        self.assertEqual(http.call_count, 1)
        self.assertEqual(json.loads(http.call_args.args[0].data), body)
        self.assertEqual(set(result["answers"]), set(body["questions"]))

    def test_fallback_commands_keep_freeze_protocol_and_are_counted_separately(self):
        harness = test_combat.CombatTests()
        report, events, _, _ = harness.simulated_loop(stepped=True, policy=POLICY)
        self.assertEqual(report["reason"], "decision_budget")
        self.assertEqual(report["applied_jev_decisions"], 0)
        self.assertEqual(report["applied_fallback_decisions"], 3)
        responses = [event for event in events if event["event"] == "response"]
        self.assertTrue(all(event["frozen_throughout"] for event in responses))
        commands = [event["command"] for event in events if event["event"] == "command"
                    and event["command"]["decision_source"] == "jev_fallback"]
        self.assertEqual(len(commands), 3)
        self.assertTrue(all(command["issued_at_frame"] == command["observed_frame"] for command in commands))
        self.assertTrue(all("selection_reason" in command for command in commands))


class PostureAndThresholdTests(unittest.TestCase):
    """Carl's answers of 2026-09-20: spacing, risk against health, and per-action floors."""

    def test_posture_comes_from_health_and_says_what_it_can_afford(self):
        from brain.decisions import health_posture
        self.assertIsNone(health_posture(None))
        self.assertEqual(health_posture(8)["posture"], "healthy")
        self.assertTrue(health_posture(8)["can_afford_a_hit"])
        self.assertEqual(health_posture(5)["posture"], "careful")
        self.assertEqual(health_posture(3)["posture"], "fragile")
        self.assertFalse(health_posture(2)["can_afford_a_hit"])
        self.assertEqual(health_posture(0)["posture"], "critical")

    def test_each_objective_has_its_own_floor_and_escape_is_highest(self):
        from brain.decisions import THRESHOLDS, ESCAPE_THRESHOLD
        # Being wrong about an attack costs a missed shot; being wrong about position costs
        # health, and an escape is never left to an uncertain answer.
        self.assertLess(THRESHOLDS["attack"], THRESHOLDS["pickup"])
        self.assertLess(THRESHOLDS["pickup"], THRESHOLDS["position"])
        self.assertGreater(ESCAPE_THRESHOLD, max(THRESHOLDS.values()))

    def test_spacing_is_wider_beside_a_boss(self):
        from brain.decisions import spacing_for, SPACING
        self.assertEqual(spacing_for({}), SPACING["default"])
        self.assertEqual(spacing_for({"boss_hull_near": True}), SPACING["boss_part"])
        self.assertGreater(SPACING["boss_part"], SPACING["default"])


if __name__ == "__main__":
    unittest.main()
