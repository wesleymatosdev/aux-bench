#!/usr/bin/env python3
"""Unit tests for the zcode-concurrency harness: check.sh and analyze.py.

Runs entirely against seeded fixtures — no zcode invocation, no network.
Usage: python3 tests/test_harness.py   (or: python3 -m unittest discover tests)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LANE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_SH = os.path.join(LANE_DIR, "check.sh")
ANALYZE_PY = os.path.join(LANE_DIR, "analyze.py")

VALID_OUT_JSON = {
    "bench": "zcode-concurrency",
    "year": 2026,
    "constants": {"width": 128, "height": 64, "offset": 7},
}


def write_meta(run_dir, status="completed", exit_code="0", duration_ms=1000, task_sha="deadbeef"):
    with open(os.path.join(run_dir, "meta.json"), "w") as fh:
        json.dump({
            "run": 1, "pid": 1, "status": status, "exit_code": exit_code,
            "duration_ms": duration_ms, "task_sha256": task_sha,
            "recorded_at_unix": 0,
        }, fh)


def seed_passing_run(run_dir):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "f1.txt"), "w") as fh:
        fh.write("zcode-bench-2026\n")
    with open(os.path.join(run_dir, "f2.txt"), "w") as fh:
        fh.write("8199\n")
    with open(os.path.join(run_dir, "f3.py"), "w") as fh:
        fh.write(
            "def rotl(n, b):\n"
            "    return ((n << b) | (n >> (32 - b))) & 0xFFFFFFFF\n"
            "if __name__ == '__main__':\n"
            "    print(rotl(0xC0FFEE00, 8))\n"
        )
    with open(os.path.join(run_dir, "out.json"), "w") as fh:
        json.dump(VALID_OUT_JSON, fh)
    with open(os.path.join(run_dir, "manifest.txt"), "w") as fh:
        fh.write("f1.txt\nf2.txt\nf3.py\nout.json\n")
    write_meta(run_dir)


class TestCheckSh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="zcb-check-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_check(self, run_dir):
        proc = subprocess.run([CHECK_SH, run_dir], capture_output=True, text=True)
        checks_path = os.path.join(run_dir, "checks.json")
        checks = json.load(open(checks_path)) if os.path.isfile(checks_path) else None
        return proc, checks

    def test_all_pass_on_correct_seeded_run(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        proc, checks = self.run_check(run_dir)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(checks["all_passed"])
        self.assertEqual(checks["passed_count"], 5)
        for s in ("s1", "s2", "s3", "s4", "s5"):
            self.assertTrue(checks["subtasks"][s]["passed"], s)

    def test_s1_content_mismatch_fails_only_s1(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "f1.txt"), "w") as fh:
            fh.write("wrong-content\n")
        proc, checks = self.run_check(run_dir)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(checks["subtasks"]["s1"]["passed"])
        self.assertTrue(checks["subtasks"]["s2"]["passed"])
        self.assertEqual(checks["passed_count"], 4)

    def test_s2_missing_file_reported_as_missing_not_fabricated(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        os.remove(os.path.join(run_dir, "f2.txt"))
        proc, checks = self.run_check(run_dir)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(checks["subtasks"]["s2"]["passed"])
        self.assertIn("missing file", checks["subtasks"]["s2"]["failures"][0])

    def test_s3_broken_python_fails_via_nonzero_exit(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "f3.py"), "w") as fh:
            fh.write("raise SystemExit(1)\n")
        proc, checks = self.run_check(run_dir)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(checks["subtasks"]["s3"]["passed"])

    def test_s3_wrong_rotl_output_fails(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "f3.py"), "w") as fh:
            fh.write("print(0)\n")
        proc, checks = self.run_check(run_dir)
        self.assertFalse(checks["subtasks"]["s3"]["passed"])

    def test_s4_invalid_json_fails(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "out.json"), "w") as fh:
            fh.write("{not valid json,}")
        proc, checks = self.run_check(run_dir)
        self.assertFalse(checks["subtasks"]["s4"]["passed"])
        self.assertIn("invalid JSON", checks["subtasks"]["s4"]["failures"][0])

    def test_s4_data_altered_fails_even_if_valid_json(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        altered = dict(VALID_OUT_JSON)
        altered["year"] = 1999
        with open(os.path.join(run_dir, "out.json"), "w") as fh:
            json.dump(altered, fh)
        proc, checks = self.run_check(run_dir)
        self.assertFalse(checks["subtasks"]["s4"]["passed"])

    def test_s5_unsorted_manifest_fails(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "manifest.txt"), "w") as fh:
            fh.write("out.json\nf1.txt\nf2.txt\nf3.py\n")
        proc, checks = self.run_check(run_dir)
        self.assertFalse(checks["subtasks"]["s5"]["passed"])

    def test_s5_extra_file_listed_fails(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        with open(os.path.join(run_dir, "manifest.txt"), "w") as fh:
            fh.write("f1.txt\nf2.txt\nf3.py\nmanifest.txt\nout.json\n")
        proc, checks = self.run_check(run_dir)
        self.assertFalse(checks["subtasks"]["s5"]["passed"])

    def test_timeout_status_propagated_not_conflated_with_model_failure(self):
        """A timeout run can still fully complete its files (killed after finishing
        writes) — checks.json must report status=timeout from meta.json while
        subtask correctness is scored independently."""
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        write_meta(run_dir, status="timeout", exit_code="137")
        proc, checks = self.run_check(run_dir)
        self.assertEqual(checks["status"], "timeout")
        self.assertTrue(checks["all_passed"])  # correctness and timeout are independent axes

    def test_missing_meta_json_reported_as_unknown_status(self):
        run_dir = os.path.join(self.tmp, "run-1")
        seed_passing_run(run_dir)
        os.remove(os.path.join(run_dir, "meta.json"))
        proc, checks = self.run_check(run_dir)
        self.assertEqual(checks["status"], "unknown")


class TestAnalyzePy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="zcb-analyze-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed_lane(self, lane_name, run_specs):
        """run_specs: list of (status, duration_ms, passed_count, all_passed)"""
        lane_dir = os.path.join(self.tmp, lane_name)
        os.makedirs(lane_dir, exist_ok=True)
        for i, (status, duration_ms, passed_count, all_passed) in enumerate(run_specs, start=1):
            run_dir = os.path.join(lane_dir, f"run-{i}")
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "meta.json"), "w") as fh:
                json.dump({
                    "run": i, "pid": i, "status": status, "exit_code": "0",
                    "duration_ms": duration_ms, "task_sha256": "x",
                    "recorded_at_unix": 0,
                }, fh)
            subtasks = {s: {"name": s, "passed": j < passed_count, "failures": []}
                        for j, s in enumerate(["s1", "s2", "s3", "s4", "s5"])}
            with open(os.path.join(run_dir, "checks.json"), "w") as fh:
                json.dump({
                    "run": f"run-{i}", "status": status, "subtasks": subtasks,
                    "passed_count": passed_count, "all_passed": all_passed,
                }, fh)
        with open(os.path.join(lane_dir, "env-before.txt"), "w") as fh:
            fh.write("date: 2026-09-03 19:00:00 -0300\nzcode_version: 0.16.5\n"
                      "memory: System-wide memory free percentage: 50%\n"
                      "system_wide_zcode_cli_procs: 1\n")
        return lane_dir

    def run_analyze(self, results_dir, out_path):
        proc = subprocess.run(
            [sys.executable, ANALYZE_PY, results_dir, "--out", out_path],
            capture_output=True, text=True,
        )
        return proc

    def test_single_lane_aggregation_matches_inputs(self):
        self.seed_lane("c1", [("completed", 20000, 5, True)])
        out = os.path.join(self.tmp, "summary.json")
        proc = self.run_analyze(self.tmp, out)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        summary = json.load(open(out))
        self.assertEqual(len(summary["lanes"]), 1)
        lane = summary["lanes"][0]
        self.assertEqual(lane["concurrency"], 1)
        self.assertEqual(lane["completed"], 1)
        self.assertEqual(lane["timeouts"], 0)
        self.assertEqual(lane["latency_ms_completed_only"]["p50"], 20000)

    def test_timeouts_counted_separately_never_as_failure(self):
        self.seed_lane("c4", [
            ("completed", 10000, 5, True),
            ("completed", 12000, 5, True),
            ("timeout", 900000, 2, False),
            ("timeout", 900000, 0, False),
        ])
        out = os.path.join(self.tmp, "summary.json")
        self.run_analyze(self.tmp, out)
        summary = json.load(open(out))
        lane = summary["lanes"][0]
        self.assertEqual(lane["timeouts"], 2)
        self.assertEqual(lane["completed"], 2)
        # timeouts must not pollute completed-only latency stats
        self.assertEqual(lane["latency_ms_completed_only"]["max"], 12000)

    def test_missing_checks_reported_as_missing_not_imputed(self):
        lane_dir = self.seed_lane("c2", [("completed", 5000, 5, True)])
        # second run dir with no meta/checks at all
        os.makedirs(os.path.join(lane_dir, "run-2"), exist_ok=True)
        out = os.path.join(self.tmp, "summary.json")
        self.run_analyze(self.tmp, out)
        summary = json.load(open(out))
        lane = summary["lanes"][0]
        self.assertEqual(lane["missing"], 1)
        self.assertEqual(lane["runs"], 2)

    def test_degradation_ratio_vs_baseline(self):
        self.seed_lane("c1", [("completed", 10000, 5, True)])
        self.seed_lane("c4", [
            ("completed", 20000, 5, True),
            ("completed", 20000, 5, True),
        ])
        out = os.path.join(self.tmp, "summary.json")
        self.run_analyze(self.tmp, out)
        summary = json.load(open(out))
        lanes = {l["lane"]: l for l in summary["lanes"]}
        self.assertEqual(lanes["c1"]["vs_baseline"]["p50_ratio"], 1.0)
        self.assertEqual(lanes["c4"]["vs_baseline"]["p50_ratio"], 2.0)

    def test_subtask_pass_rate_reflects_partial_failures(self):
        self.seed_lane("c1", [
            ("completed", 1000, 5, True),
            ("completed", 1000, 3, False),  # s4, s5 fail per seed_lane's index scheme
        ])
        out = os.path.join(self.tmp, "summary.json")
        self.run_analyze(self.tmp, out)
        summary = json.load(open(out))
        lane = summary["lanes"][0]
        # s1-s3 pass in both runs, s4/s5 pass only in the first
        self.assertEqual(lane["subtask_pass_counts"]["s1"], 2)
        self.assertEqual(lane["subtask_pass_counts"]["s4"], 1)
        self.assertEqual(lane["subtask_pass_counts"]["s5"], 1)

    def test_no_lanes_found_raises(self):
        empty_dir = os.path.join(self.tmp, "empty")
        os.makedirs(empty_dir)
        proc = self.run_analyze(empty_dir, os.path.join(self.tmp, "out.json"))
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
