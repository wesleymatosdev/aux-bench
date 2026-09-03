#!/usr/bin/env bash
# Deterministic checker for one zcode-concurrency run directory.
#
# Usage: check.sh <run-dir>
#
# PASS/FAIL per sub-task; writes <run-dir>/checks.json. Never repairs,
# never re-runs the model. Missing files are recorded as missing.
# Exit code 0 iff all five sub-tasks pass (so the smoke lane can gate the ramp).

set -u
RUN_DIR="${1:?usage: check.sh <run-dir>}"
[ -d "$RUN_DIR" ] || { echo "FATAL: no such run dir: $RUN_DIR" >&2; exit 2; }

python3 - "$RUN_DIR" <<'PYEOF'
import json, os, subprocess, sys

run_dir = sys.argv[1]
os.chdir(run_dir)

# The seeded in.json (runner.sh) is invalid JSON with trailing commas; this is
# the data a correct out.json must preserve exactly.
EXPECTED_DATA = {
    "bench": "zcode-concurrency",
    "year": 2026,
    "constants": {"width": 128, "height": 64, "offset": 7},
}
S3_EXPECTED = {"4293787840", "0xffee00c0"}  # rotl(0xC0FFEE00, 8), decimal or hex
S5_EXPECTED = ["f1.txt", "f2.txt", "f3.py", "out.json"]

def exact_one_line(path, expected):
    """Exactly `expected`, with at most one trailing newline."""
    if not os.path.isfile(path):
        return False, "missing file"
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if text != expected:
        return False, f"content mismatch: got {text!r} (want {expected!r})"
    return True, ""

results = {}

ok, why = exact_one_line("f1.txt", "zcode-bench-2026")
results["s1"] = {"name": "f1_exact_content", "passed": ok, "failures": [] if ok else [why]}

ok, why = exact_one_line("f2.txt", "8199")  # 128*64+7
results["s2"] = {"name": "f2_exact_value", "passed": ok, "failures": [] if ok else [why]}

if not os.path.isfile("f3.py"):
    results["s3"] = {"name": "f3_rotl_executes", "passed": False, "failures": ["missing file"]}
else:
    try:
        proc = subprocess.run(
            ["python3", "f3.py"], capture_output=True, text=True, timeout=10
        )
        got = proc.stdout.strip().lower()
        if proc.returncode != 0:
            results["s3"] = {"name": "f3_rotl_executes", "passed": False,
                             "failures": [f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"]}
        elif got not in S3_EXPECTED:
            results["s3"] = {"name": "f3_rotl_executes", "passed": False,
                             "failures": [f"output mismatch: got {got!r} (want 4293787840 / 0xffee00c0)"]}
        else:
            results["s3"] = {"name": "f3_rotl_executes", "passed": True, "failures": []}
    except subprocess.TimeoutExpired:
        results["s3"] = {"name": "f3_rotl_executes", "passed": False, "failures": ["checker timeout (10s)"]}

if not os.path.isfile("out.json"):
    results["s4"] = {"name": "out_json_valid_and_preserved", "passed": False, "failures": ["missing file"]}
else:
    try:
        with open("out.json") as fh:
            data = json.load(fh)
        if data != EXPECTED_DATA:
            results["s4"] = {"name": "out_json_valid_and_preserved", "passed": False,
                             "failures": [f"data mismatch: {json.dumps(data, sort_keys=True)[:200]}"]}
        else:
            results["s4"] = {"name": "out_json_valid_and_preserved", "passed": True, "failures": []}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        results["s4"] = {"name": "out_json_valid_and_preserved", "passed": False,
                         "failures": [f"invalid JSON: {exc}"]}

if not os.path.isfile("manifest.txt"):
    results["s5"] = {"name": "manifest_exact_sorted", "passed": False, "failures": ["missing file"]}
else:
    with open("manifest.txt") as fh:
        lines = fh.read().rstrip("\n").split("\n")
    if lines != S5_EXPECTED:
        results["s5"] = {"name": "manifest_exact_sorted", "passed": False,
                         "failures": [f"lines {lines!r} != {S5_EXPECTED!r}"]}
    else:
        results["s5"] = {"name": "manifest_exact_sorted", "passed": True, "failures": []}

meta = {}
if os.path.isfile("meta.json"):
    meta = json.load(open("meta.json"))

checks = {
    "run": os.path.basename(os.path.normpath(run_dir)),
    "status": meta.get("status", "unknown"),  # completed | timeout | unknown (missing meta recorded as-is)
    "subtasks": results,
    "passed_count": sum(1 for r in results.values() if r["passed"]),
    "all_passed": all(r["passed"] for r in results.values()),
}
with open("checks.json", "w") as fh:
    json.dump(checks, fh, indent=2)

for key in sorted(results):
    r = results[key]
    mark = "pass" if r["passed"] else "FAIL"
    line = f"{key} {r['name']:<28} {mark}"
    if r["failures"]:
        line += "  -> " + "; ".join(r["failures"])
    print(line)
print(f"status={checks['status']} passed {checks['passed_count']}/5")
sys.exit(0 if checks["all_passed"] else 1)
PYEOF
