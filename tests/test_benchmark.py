"""Outcome comparisons include partial practice entries and disclose missing data."""
import sys
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # the code under test lives in src/
import json
from pathlib import Path
import tempfile
import unittest

from benchmark import entry_kind, score


class BenchmarkTests(unittest.TestCase):
    def score_run(self, start, end, hit_frames=(), kills=()):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "manifest.json").write_text(json.dumps({"run_label":1}))
            (run / "summary.json").write_text(json.dumps({"first_request_frame":start,"final_frame":end}))
            events = {"hit_marker_frames":list(hit_frames),
                      "aircraft_destroyed":[{"frame":frame} for frame in kills]}
            (run / "decision_trace.json").write_text(json.dumps({"candidate_table_events":events}))
            return score(run)

    def test_boss_practice_and_early_death_are_counted(self):
        result = self.score_run(24134, 24200, (24150,), (24160,))
        self.assertEqual(result["segments"], {
            "boss":{"kills":1,"hits":1,"frames":66,"complete":False}})

    def test_boundary_events_belong_to_one_segment(self):
        result = self.score_run(20663, 22201, (21400,), (21400,))
        self.assertEqual(result["segments"]["opening"]["kills"], 0)
        self.assertEqual(result["segments"]["middle"]["kills"], 1)
        self.assertEqual(sum(s["hits"] for s in result["segments"].values()), 1)

    def test_entry_groups_separate_full_level_and_practice(self):
        self.assertEqual([entry_kind(start) for start in (None,20663,22213,24134)],
                         ["unstarted","full","practice","boss"])

    def test_outcomes_on_final_recorded_frame_are_not_discarded(self):
        result = self.score_run(24134, 24200, (24200,), (24200,))
        self.assertEqual(result["segments"]["boss"]["hits"], 1)
        self.assertEqual(result["segments"]["boss"]["kills"], 1)


if __name__ == "__main__":
    unittest.main()
