"""Offline regression tests: HTTP is always mocked and credentials are never read."""
import argparse
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bridge


def state(frame=100, session="test-lua", epoch=0, run="test-run", **kwargs):
    return {"frame": frame, "lua_session_id": session, "reload_epoch": epoch,
            "bridge_run_id": run, "player_y_candidate": 112, **kwargs}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-unit-", dir=bridge.RUNS)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(bridge.RUNS.resolve()))
        self.log = self.root / "run.jsonl"
        self.addCleanup(self.temp.cleanup)

    def test_partial_or_invalid_state_is_not_frame_zero(self):
        path = self.root / "state.json"
        with patch.object(bridge, "STATE", path):
            for raw in ('{"frame":', '[]', 'null', '{"frame":true}', '{"frame":-1}'):
                path.write_text(raw)
                self.assertIsNone(bridge.read_state())
            path.write_text(json.dumps(state()))
            self.assertEqual(bridge.read_state()["frame"], 100)

    def test_fresh_start_requires_this_run_and_same_session_advancement(self):
        observations = [state(99999, run="old-run"), None, state(100), state(100),
                        state(20, session="new-lua"), state(21, session="new-lua")]
        with patch.object(bridge, "ROOT", self.root), patch.object(bridge, "read_state", side_effect=observations), patch.object(bridge.time, "sleep"):
            fresh = bridge.wait_for_fresh_state("test-run")
        self.assertEqual(fresh["frame"], 21)

    def test_epoch_change_restarts_freshness_baseline(self):
        observations = [state(100), state(200, epoch=1), state(201, epoch=1)]
        with patch.object(bridge, "ROOT", self.root), patch.object(bridge, "read_state", side_effect=observations), patch.object(bridge.time, "sleep"):
            self.assertEqual(bridge.wait_for_fresh_state("test-run")["frame"], 201)

    def test_failed_replace_never_truncates_existing_action(self):
        target = self.root / "action.json"
        target.write_text('{"action":"stop"}')
        with patch.object(Path, "replace", side_effect=PermissionError), patch.object(bridge.time, "sleep"):
            with self.assertRaises(PermissionError):
                bridge.write_json(target, {"action": "up"})
        self.assertEqual(target.read_text(), '{"action":"stop"}')

    def test_calibration_request_uses_verified_axis_not_legacy_candidate(self):
        payload = bridge.calibration_request({}, state())
        self.assertEqual(payload["state"]["player_y"], 112)
        self.assertEqual(payload["state"]["positive_y_direction"], "down")
        self.assertNotIn("vertical_position_candidate", json.dumps(payload))
        self.assertIn("Calibration only", payload["questions"]["movement"]["instructions"])

    def run_mock_live(self, snapshots, confidence=1, failure=None):
        args = argparse.Namespace(calibrate=False, gun_test=False, live=True)
        response = io.BytesIO(json.dumps({"answers": {"movement": {
            "choice": "up", "confidence": confidence, "probabilities": {"up": 0.7, "hold": 0.3}}}}).encode())
        with patch.object(bridge, "ROOT", self.root), patch.object(bridge, "LOG", self.root / "legacy.log"), \
                patch.object(bridge, "read_state", side_effect=snapshots), \
                patch.object(bridge, "write_json") as writes, patch.object(bridge.time, "sleep"), \
                patch.object(bridge.urllib.request, "urlopen", return_value=response, side_effect=failure) as http, \
                patch.dict(bridge.os.environ, {"TYPESAFE_API_KEY": "unit-test-placeholder"}), patch("builtins.print"):
            bridge.run(args, {}, 1, 30, "test-run", self.log, "live", state())
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(http.call_count, 1)
        self.assertNotIn("unit-test-placeholder", self.log.read_text())
        return records, writes

    def test_stale_reply_is_logged_but_not_applied(self):
        records, writes = self.run_mock_live([state(), state(131)])
        self.assertEqual(records[-1]["event"], "stale_reply_rejected")
        self.assertEqual(records[-1]["jev_requests"], 1)
        writes.assert_not_called()

    def test_api_failure_attempt_is_counted_and_diagnostic_sanitized(self):
        records, writes = self.run_mock_live([state()], failure=OSError("secret-bearing response"))
        self.assertEqual(records[-1]["event"], "api_error")
        self.assertEqual(records[-1]["jev_requests"], 1)
        self.assertNotIn("secret-bearing", self.log.read_text())
        self.assertEqual(writes.call_args.args[1]["action"], "stop")

    def test_raw_jev_choice_is_not_overwritten_in_log(self):
        ack = {"last_applied_run_id": "test-run", "last_applied_call": 1, "first_apply_frame": 106}
        records, writes = self.run_mock_live([state(), state(105), state(106, **ack), state(136, **ack)], confidence=0.2)
        record = next(r for r in records if "resulting_action" in r)
        self.assertEqual(record["requested_action"], "up")
        self.assertEqual(record["resulting_action"]["action"], "hold")
        self.assertTrue(record["override_reason"].startswith("legacy_calibration"))
        applied = next(r for r in records if r.get("event") == "input_ack")
        self.assertEqual(applied["observe_to_apply_frames"], 6)

    def test_unreadable_state_after_final_ack_waits_for_a_real_state(self):
        # A concurrent Lua rewrite reads as None (check_bridge dry-run 20260919-140406-33db6b crashed here).
        ack = {"last_applied_run_id": "test-run", "last_applied_call": 1, "first_apply_frame": 106}
        records, writes = self.run_mock_live([state(), state(105), state(106, **ack), None, state(136, **ack)])
        self.assertEqual(sum(r.get("event") == "input_ack" for r in records), 1)
        self.assertEqual(writes.call_args.args[1]["action"], "stop")

    def test_keyboard_interrupt_still_sends_stop(self):
        with patch("sys.argv", ["bridge.py", "--dry-run"]), \
                patch.object(bridge, "RUNS", self.root), patch.object(bridge, "LOG", self.root / "legacy.log"), \
                patch.object(bridge, "release_controls") as release, \
                patch.object(bridge, "wait_for_fresh_state", return_value=state()), \
                patch.object(bridge, "run", side_effect=KeyboardInterrupt), patch("builtins.print"):
            bridge.main()
        self.assertEqual(release.call_count, 2)
        self.assertEqual(release.call_args_list[0].args[0], release.call_args_list[-1].args[0])


class KeyShadowingTests(unittest.TestCase):
    def test_nothing_inside_the_run_loop_rebinds_the_api_key(self):
        """Shadowing `key` inside the loop sent a tuple to the Authorization header, twice
        now: once as a track identity, once as a wall position."""
        import ast, inspect
        import play_segment
        source = inspect.getsource(play_segment.run)
        tree = ast.parse(source.lstrip())
        rebinds = [node.lineno for node in ast.walk(tree)
                   if isinstance(node, ast.Assign)
                   for target in node.targets
                   if isinstance(target, ast.Name) and target.id == "key"]
        self.assertEqual(rebinds, [], f"`key` is reassigned inside run() at lines {rebinds}")


if __name__ == "__main__":
    unittest.main()
