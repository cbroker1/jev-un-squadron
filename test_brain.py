"""Offline checks for reference observations, frame-based geometry, and request previews."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from brain.observations import WRAM_SIZE, SLOT, PROJECTILE_X, PROJECTILE_Y, SlotTracker, FamilyTracker, fixed24, ROM_SHA1, PROJECTILE_BASES
from brain.digest import ACTIONS, PLAYER_BOUNDS, bounded_approach, nearest_approach, summarize
from brain.questions import movement_request
import replay_brain
import observe_brain


def ram(x=120, y=112, phase=0xCC, signature=0x17):
    data = bytearray(WRAM_SIZE)
    data[SLOT:SLOT+4] = bytes([phase, 0x7F, 0xF9, 4])
    data[SLOT+8] = 1
    data[SLOT+13] = signature
    data[PROJECTILE_X:PROJECTILE_X+3] = int(round(x*256)).to_bytes(3, "little", signed=True)
    data[PROJECTILE_Y:PROJECTILE_Y+3] = int(round(y*256)).to_bytes(3, "little", signed=True)
    return data


def observation():
    tracker = SlotTracker()
    tracker.observe(ram(130, 112), 100, "fixture")
    t = tracker.observe(ram(126, 112), 102, "fixture")
    return {"source_frame": 102, "player": {"x": 96, "y": 112}, "tracks": [t]}


class BrainTests(unittest.TestCase):
    def test_negative_coordinate_does_not_wrap_to_right_edge(self):
        data = ram(-2.21875, 140.03125)
        self.assertEqual(fixed24(data, PROJECTILE_X), -2.21875)
        self.assertFalse(SlotTracker().observe(data, 100, "test")["on_screen"])

    def test_first_sample_has_unknown_velocity(self):
        self.assertIsNone(SlotTracker().observe(ram(), 100, "test")["vx"])

    def test_velocity_uses_elapsed_game_frames(self):
        t = SlotTracker()
        t.observe(ram(120, 100), 100, "test")
        result = t.observe(ram(112, 104), 104, "test")
        self.assertEqual((result["vx"], result["vy"]), (-2, 1))

    def test_rewind_session_epoch_and_gap_clear_velocity(self):
        for frame, session, epoch in [(90, "test", 0), (104, "new", 0), (104, "test", 1), (120, "test", 0), (100, "test", 0)]:
            t = SlotTracker()
            t.observe(ram(), 100, "test")
            result = t.observe(ram(112), frame, session, epoch)
            self.assertIsNone(result["vx"])
            self.assertEqual(result["generation"], 2)

    def test_inactive_and_transition_bytes_break_identity(self):
        for phase in (0, 0xC0):
            t = SlotTracker()
            t.observe(ram(), 100, "test")
            result = t.observe(ram(118, phase=phase), 102, "test")
            self.assertEqual(result["phase"], "inactive_or_unclassified")
            new = t.observe(ram(180), 104, "test")
            self.assertIsNone(new["vx"])
            self.assertEqual(new["generation"], 2)

    def test_changed_signature_or_position_jump_breaks_identity(self):
        for next_ram in (ram(118, signature=0x1C), ram(200)):
            t = SlotTracker()
            t.observe(ram(), 100, "test")
            self.assertIsNone(t.observe(next_ram, 102, "test")["vx"])

    def test_our_shot_is_not_the_investigated_enemy_slot(self):
        data = bytearray(WRAM_SIZE)
        data[0x1091], data[0x1094] = 180, 112
        self.assertEqual(SlotTracker().observe(data, 100, "test")["phase"], "inactive_or_unclassified")

    def test_family_slots_have_independent_identity_and_velocity(self):
        data = ram(120)
        data[0x1B00:0x1B40] = ram(200)[SLOT:SLOT+64]
        tracker = FamilyTracker()
        first = tracker.observe(data, 100, "test")
        data = ram(116)
        data[0x1B00:0x1B40] = ram(202)[SLOT:SLOT+64]
        second = tracker.observe(data, 102, "test")
        self.assertEqual((second[0]["vx"], second[1]["vx"]), (-2, 1))
        self.assertNotEqual(second[0]["slot"], second[1]["slot"])
        data[SLOT] = 0
        third = tracker.observe(data, 104, "test")
        self.assertEqual(third[0]["phase"], "inactive_or_unclassified")
        self.assertEqual(third[1]["generation"], first[1]["generation"])

    def test_unknown_slots_are_not_accepted_by_inferred_stride(self):
        with self.assertRaises(ValueError):
            SlotTracker(base=0x1C40)

    def test_bridge_bytes_decode_like_full_wram_and_validate_profile(self):
        data = ram(-2.21875, 140.03125)
        state = {"frame": 100, "lua_session_id": "fixture", "reload_epoch": 0,
                 "observation_profile": {"schema": 1, "domain": "WRAM", "rom_hash": ROM_SHA1,
                    "slots": [{"base": base, "bytes_hex": data[base:base+22].hex()} for base in PROJECTILE_BASES]}}
        expected = FamilyTracker().observe(data, 100, "fixture")
        self.assertEqual(FamilyTracker().observe_bridge(state), expected)
        for mutation in ({"rom_hash": "wrong"}, {"schema": 0}, {"domain": "VRAM"}, {"slots": []}):
            invalid = dict(state, observation_profile=state["observation_profile"] | mutation)
            with self.assertRaises(ValueError):
                FamilyTracker().observe_bridge(invalid)

    def test_measured_intervention_matches_forecast_without_network(self):
        from verify_forecast import compare
        root = Path(__file__).parent / "hazard_observation"
        reference, actual = root / "probe_20260919-114543-d95c1f_neutral", root / "probe_20260919-120911-629b88_neutral"
        if not actual.exists():
            self.skipTest("Local intervention evidence is not present")
        with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            result = compare(reference, actual)
        self.assertTrue(result["pass"])
        self.assertFalse(result["forecast_uses_future_data"])
        self.assertEqual((result["max_player_error_px"], result["max_projectile_error_px"]), (0, 0))

    def test_passive_watch_ignores_duplicate_frames_and_keeps_physical_input_distinct(self):
        with tempfile.TemporaryDirectory(prefix="observer-unit-", dir=observe_brain.ROOT / "runs") as temp:
            folder = Path(temp)
            data = ram()
            base = {"lua_session_id": "fixture", "reload_epoch": 0, "bridge_run_id": folder.name,
                    "player_x_candidate": 96, "player_y_candidate": 112,
                    "input_poll_mask": 4, "requested_mask": 0,
                    "observation_profile": {"schema": 1, "domain": "WRAM", "rom_hash": ROM_SHA1,
                        "slots": [{"base": slot, "bytes_hex": data[slot:slot+22].hex()} for slot in PROJECTILE_BASES]}}
            fresh = dict(base, frame=100)
            states = [fresh, fresh] + [dict(base, frame=frame) for frame in range(101,131)]
            with patch.object(observe_brain.bridge, "release_controls") as stop, \
                    patch.object(observe_brain.bridge, "wait_for_fresh_state", return_value=fresh), \
                    patch.object(observe_brain.bridge, "read_state", side_effect=states), \
                    patch.object(observe_brain.time, "sleep"), patch("builtins.print"), \
                    patch("socket.socket", side_effect=AssertionError("Network forbidden")):
                report = observe_brain.watch(folder, 30, 30)
            self.assertEqual(report["observations"], 31)
            self.assertEqual(report["previews"], 2)
            self.assertEqual(report["nonzero_injected_observations"], 0)
            stop.assert_called_once_with(folder.name, 0)
            records = [json.loads(line) for line in (folder / "brain_stream.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["interval_since_previous_preview_frames"], 30)
            self.assertEqual(records[-1]["observed_state"]["actual_input_poll_mask"], 4)
            self.assertTrue(all(r["requested_action"] is None and r["applied_action"] is None for r in records))

    def test_passive_watch_ends_before_decoding_a_reloaded_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="observer-unit-", dir=observe_brain.ROOT / "runs") as temp:
            folder = Path(temp)
            fresh = {"frame": 100, "lua_session_id": "fixture", "reload_epoch": 0, "bridge_run_id": folder.name}
            changed = dict(fresh, frame=80, reload_epoch=1)
            with patch.object(observe_brain.bridge, "release_controls"), \
                    patch.object(observe_brain.bridge, "wait_for_fresh_state", return_value=fresh), \
                    patch.object(observe_brain.bridge, "read_state", return_value=changed), patch("builtins.print"):
                report = observe_brain.watch(folder, 30, 30)
            self.assertEqual(report["reason"], "reload_or_session_change")
            self.assertEqual(report["observations"], 0)

    def test_closest_approach_is_clamped_to_horizon(self):
        self.assertEqual(nearest_approach(20, 0, -1, 0, 10), (10, 10))
        self.assertEqual(nearest_approach(20, 0, 1, 0, 10), (20, 0))

    def test_hold_is_not_automatically_safe(self):
        result = summarize(observation())
        self.assertEqual(result["actions"]["hold"]["closest_anchor_distance_px"], 0)
        self.assertGreater(result["actions"]["up"]["closest_anchor_distance_px"], 0)
        self.assertFalse(result["live_control_ready"])

    def test_y_up_decreases_and_respects_tested_bound(self):
        obs = observation()
        obs["player"]["y"] = 62
        result = summarize(obs)
        self.assertEqual(result["actions"]["up"]["projected_position"], [96, 48])
        self.assertEqual(result["actions"]["up"]["boundary_margin_px"], 0)

    def test_clamped_forecast_matches_dense_numerical_check(self):
        projectile = {"x": 60, "y": 90, "vx": -1.5, "vy": 0.5}
        actual, _ = bounded_approach(46, 112, -1, 0, projectile, 20)
        import math
        dense = min(math.hypot(60-1.5*i/100-max(16,46-2.5*i/100),90+0.5*i/100-112) for i in range(2001))
        self.assertAlmostEqual(actual, dense, places=3)

    def test_empty_or_stale_track_is_unknown_not_clear(self):
        obs = observation()
        obs["tracks"] = []
        result = summarize(obs)
        for value in result["actions"].values():
            self.assertIsNone(value["closest_anchor_distance_px"])
            self.assertIn("does not mean", value["description"])

    def test_invalid_player_position_is_not_projected_as_alive(self):
        obs = observation()
        obs["player"]["x"] = 0
        result = summarize(obs)
        self.assertFalse(result["player_position_supported"])
        self.assertIsNone(result["actions"]["up"]["projected_position"])

    def test_choice_preview_has_all_actions_but_no_raw_ram(self):
        request = movement_request(summarize(observation()))
        self.assertEqual(set(request["questions"]["movement"]["criteria"]), set(ACTIONS))
        self.assertEqual(request["questions"]["movement"]["type"], "choice")
        self.assertNotIn("0x1AC0", json.dumps(request))
        self.assertIn("unknown", json.dumps(request))

    def test_replay_works_with_network_forbidden(self):
        capture = Path(__file__).parent / "hazard_observation/probe_20260919-114543-d95c1f_neutral"
        if not capture.exists():
            self.skipTest("Local evidence capture is not present")
        root = Path(__file__).parent.resolve()
        with tempfile.TemporaryDirectory(prefix="brain-unit-", dir=root / "runs") as temp:
            target = Path(temp)
            self.assertTrue(target.resolve().is_relative_to(root / "runs"))
            (target / "runs").mkdir()
            with patch.object(replay_brain, "ROOT", target), patch("sys.argv", ["replay_brain.py", str(capture)]), \
                    patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch("builtins.print"):
                replay_brain.main()
            manifest = json.loads(next((target / "runs").glob("*/manifest.json")).read_text())
            self.assertEqual(manifest["jev_requests"], 0)
            self.assertEqual(manifest["controller_writes"], 0)


if __name__ == "__main__":
    unittest.main()
