"""Released-run accounting never shrinks the denominator."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.fdb3_verify_released import summarize


class VerifyReleasedTests(unittest.TestCase):
    def layout(self, root, statuses):
        for index, status in enumerate(statuses):
            directory = Path(root) / f"case_{index}"
            directory.mkdir()
            (directory / "input.wav").write_bytes(b"")
            if status is not None:
                (directory / "result_thread.json").write_text(json.dumps({"status": status, "actual_tool_calls": []}))

    def report(self, root, total, passed):
        path = Path(root) / "report.json"
        path.write_text(json.dumps({"total_scenarios": total, "passed": passed, "failed": total - passed}))
        return path

    def test_all_complete_and_passing_is_zero(self):
        with tempfile.TemporaryDirectory() as root:
            self.layout(root, ["completed"] * 3)
            self.assertEqual(summarize(root, "thread", self.report(root, 3, 3), expected=3)["exit_code"], 0)

    def test_complete_but_not_all_passing_is_one(self):
        with tempfile.TemporaryDirectory() as root:
            self.layout(root, ["completed"] * 3)
            self.assertEqual(summarize(root, "thread", self.report(root, 3, 2), expected=3)["exit_code"], 1)

    def test_missing_failed_or_unjudged_is_two(self):
        for statuses, report in ((["completed", None, "completed"], (3, 2)),
                                 (["completed", "inference_failed", "completed"], (3, 2)),
                                 (["completed"] * 3, None), (["completed"] * 3, (2, 2))):
            with self.subTest(statuses=statuses, report=report):
                with tempfile.TemporaryDirectory() as root:
                    self.layout(root, statuses)
                    path = self.report(root, *report) if report else None
                    self.assertEqual(summarize(root, "thread", path, expected=3)["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
