"""Offline tests for the Jev Squadron dashboard. No server, no emulator, no API."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class DashboardTests(unittest.TestCase):
    def test_tail_events_survives_a_half_written_line(self):
        """The dashboard reads a file the runner is still appending to."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.write_text('{"event": "request", "attempt": 1}\n'
                            '{"event": "response", "attempt": 1}\n'
                            '{"event": "request", "attempt": 2, "partial"')     # torn write
            events = dashboard.tail_events(path, ("request", "response"), 10)
            self.assertEqual([e["event"] for e in events], ["request", "response"])

    def test_tail_events_returns_the_most_recent_first_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.write_text("".join(f'{{"event": "request", "attempt": {i}}}\n' for i in range(20)))
            events = dashboard.tail_events(path, ("request",), 3)
            self.assertEqual([e["attempt"] for e in events], [17, 18, 19])

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(dashboard.tail_events(Path("nowhere.jsonl"), ("request",), 5), [])

    def test_option_story_reads_the_chosen_option_only(self):
        digest = {"actions": {
            "left": {"targets_the_gun_would_hit": 1, "soonest_hit_kind": "ground_tank",
                     "soonest_hit_frames": 9, "targets_behind": 2,
                     "nearest_target_behind_kind": "ground_tank",
                     "frames_to_get_behind_nearest_target_behind": 22,
                     "closest_anchor_distance_px": 40.0, "enemy_body_anchor_gap_px": 31.0,
                     "closest_threat_direction": "below, right"},
            "right": {"targets_the_gun_would_hit": 0, "aim_error_px": 14.0}}}
        story = dict(dashboard.option_story(digest, "left"))
        self.assertIn("ground tank in 9 frames", story["SHOT"])
        self.assertIn("22 frames to get past", story["BEHIND"])
        self.assertEqual(story["CLOSEST"], "31 px below, right")
        self.assertNotIn("AIM", story)                       # that belongs to the other option
        self.assertIn("AIM", dict(dashboard.option_story(digest, "right")))
        self.assertEqual(dashboard.option_story(digest, "nonexistent"), [])

    def test_uncatchable_target_behind_is_said_plainly(self):
        digest = {"actions": {"hold": {"targets_behind": 1, "nearest_target_behind_kind": "enemy_aircraft",
                                       "frames_to_get_behind_nearest_target_behind": None}}}
        self.assertIn("cannot be caught", dict(dashboard.option_story(digest, "hold"))["BEHIND"])

    def test_live_state_is_idle_without_an_active_run(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(dashboard, "RUNS", Path(folder)):
                self.assertEqual(dashboard.live_state(), {"running": False})
                (Path(folder) / "active_segment.json").write_text("{not json")
                self.assertEqual(dashboard.live_state(), {"running": False})

    def test_live_state_follows_the_active_run_and_reports_the_last_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "combat-unit-live"
            run.mkdir()
            (run / "manifest.json").write_text(json.dumps({"run_label": 42, "mode": "live"}))
            (run / "events.jsonl").write_text(
                json.dumps({"event": "request", "attempt": 7,
                            "observation": {"source_frame": 21000, "scroll_x": 800,
                                            "player": {"x": 96, "y": 112},
                                            "tracks": [{"kind": "enemy_aircraft", "x": 200.0, "y": 100.0,
                                                        "vx": -1.8, "vy": 0.0,
                                                        "phase": "observed_moving_signature"},
                                                       {"kind": "unclassified", "x": 10.0, "y": 10.0,
                                                        "vx": 0.0, "vy": 0.0,
                                                        "phase": "observed_moving_signature"}]},
                            "digest": {"actions": {"up": {"aim_error_px": 8.0}}}})+"\n"
                + json.dumps({"event": "response", "attempt": 7, "source_frame": 21000,
                              "latency_ms": 250.0, "decision_source": "jev",
                              "response": {"choice": "up", "confidence": 0.6,
                                           "probabilities": {"up": 0.7, "down": 0.3}}})+"\n")
            (root / "active_segment.json").write_text(json.dumps({"running": True, "run_dir": str(run)}))
            with patch.object(dashboard, "RUNS", root):
                live = dashboard.live_state()
            self.assertTrue(live["running"])
            self.assertEqual(live["run_label"], 42)
            self.assertEqual(live["frame"], 21000)
            self.assertEqual(live["judgment"]["choice"], "up")
            self.assertEqual(live["judgment"]["probabilities"], {"up": 0.7, "down": 0.3})
            self.assertEqual(live["feed"][-1]["attempt"], 7)
            # Only classified objects are drawn; an unclassified record is not invented into one.
            self.assertEqual([t["kind"] for t in live["tracks"]], ["enemy_aircraft"])
            self.assertEqual(live["counts"]["enemy_aircraft"], 1)

    def test_a_finished_run_stops_showing_as_running(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "combat-unit-live"
            run.mkdir()
            (run / "events.jsonl").write_text(json.dumps({"event": "finished", "reason": "game_frame_budget"})+"\n")
            (root / "active_segment.json").write_text(json.dumps({"running": True, "run_dir": str(run)}))
            with patch.object(dashboard, "RUNS", root):
                live = dashboard.live_state()
            self.assertFalse(live["running"])
            self.assertEqual(live["finished"]["reason"], "game_frame_budget")


if __name__ == "__main__":
    unittest.main()
