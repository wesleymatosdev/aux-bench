#!/usr/bin/env python3
"""Aggregate zcode-concurrency lanes into results/summary.json + a table.

Usage: analyze.py <lane-results-dir> [--out results/summary.json]

Reads every c<N>/ lane directory written by runner.sh. Per lane: run count,
completed vs timeout vs missing, per-subtask correctness, wall-clock
p50/p95/max over completed runs, and latency degradation vs the first lane.
Timeouts are counted as their own class and NEVER as model failure; runs with
no checks.json are reported as missing — nothing is imputed.
"""

import argparse
import glob
import json
import os
import re
import statistics
import time

SUBTASKS = ["s1", "s2", "s3", "s4", "s5"]


def percentile(values, pct):
    """Linear-interpolation percentile (numpy default), for small n."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * pct / 100.0
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def fmt_ms(v):
    return "-" if v is None else f"{int(round(v)):,}ms"


def analyze_lane(lane_dir):
    m = re.match(r"c(\d+)$", os.path.basename(os.path.normpath(lane_dir)))
    concurrency = int(m.group(1))
    run_dirs = sorted(
        glob.glob(os.path.join(lane_dir, "run-*")),
        key=lambda d: int(re.search(r"run-(\d+)$", d).group(1)),
    )

    durations_completed, timeouts, missing = [], 0, 0
    sub_pass = {s: 0 for s in SUBTASKS}
    checked = 0
    per_run = []
    for rd in run_dirs:
        meta_p, checks_p = os.path.join(rd, "meta.json"), os.path.join(rd, "checks.json")
        meta = json.load(open(meta_p)) if os.path.isfile(meta_p) else None
        checks = json.load(open(checks_p)) if os.path.isfile(checks_p) else None
        if meta is None or checks is None:
            missing += 1
            per_run.append({"run": os.path.basename(rd), "status": "missing"})
            continue
        entry = {
            "run": os.path.basename(rd),
            "status": meta.get("status", "unknown"),
            "exit_code": meta.get("exit_code"),
            "duration_ms": meta.get("duration_ms"),
            "passed_count": checks.get("passed_count"),
            "all_passed": checks.get("all_passed"),
        }
        per_run.append(entry)
        if meta.get("status") == "timeout":
            timeouts += 1
        elif meta.get("status") == "completed":
            durations_completed.append(meta.get("duration_ms") or 0)
        checked += 1
        for s in SUBTASKS:
            r = checks.get("subtasks", {}).get(s)
            if r and r.get("passed"):
                sub_pass[s] += 1

    # Ambient load: system-wide zcode-cli counts sampled during the lane
    # (includes the lane's own N processes AND unrelated swarm workers).
    samples = []
    log = os.path.join(lane_dir, "zcode-cli-count.log")
    if os.path.isfile(log):
        for line in open(log):
            m2 = re.search(r"zcode_cli_system_wide=(\d+)", line)
            if m2:
                samples.append(int(m2.group(1)))

    env = {}
    env_p = os.path.join(lane_dir, "env-before.txt")
    if os.path.isfile(env_p):
        for line in open(env_p):
            if ":" in line:
                k, _, v = line.partition(":")
                env[k.strip()] = v.strip()

    return {
        "lane": os.path.basename(os.path.normpath(lane_dir)),
        "concurrency": concurrency,
        "runs": len(run_dirs),
        "completed": len(durations_completed),
        "timeouts": timeouts,
        "missing": missing,
        "subtask_pass_counts": {s: sub_pass[s] for s in SUBTASKS},
        "subtask_pass_rate": {
            s: (round(sub_pass[s] / checked, 4) if checked else None) for s in SUBTASKS
        },
        "latency_ms_completed_only": {
            "min": min(durations_completed) if durations_completed else None,
            "p50": percentile(durations_completed, 50),
            "p95": percentile(durations_completed, 95),
            "max": max(durations_completed) if durations_completed else None,
        },
        "zcode_cli_system_wide": {
            "samples": len(samples),
            "min": min(samples) if samples else None,
            "mean": round(statistics.mean(samples)) if samples else None,
            "max": max(samples) if samples else None,
        },
        "env_before": {k: env[k] for k in ("date", "zcode_version", "memory", "system_wide_zcode_cli_procs") if k in env},
        "per_run": per_run,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", help="dir containing c<N>/ lane directories")
    ap.add_argument("--out", default=None, help="write summary JSON here (default: <results_dir>/summary.json)")
    args = ap.parse_args()

    lanes = [analyze_lane(d) for d in sorted(
        glob.glob(os.path.join(args.results_dir, "c*")),
        key=lambda d: int(re.search(r"c(\d+)$", d.rstrip("/")).group(1)),
    ) if re.search(r"c\d+$", d.rstrip("/"))]
    if not lanes:
        sys_exit = f"no c<N> lanes found under {args.results_dir}"
        raise SystemExit(sys_exit)

    baseline = lanes[0]
    base_p50 = baseline["latency_ms_completed_only"]["p50"]
    for lane in lanes:
        p50 = lane["latency_ms_completed_only"]["p50"]
        lane["vs_baseline"] = {
            "baseline_lane": baseline["lane"],
            "p50_ratio": (round(p50 / base_p50, 3) if (p50 is not None and base_p50) else None),
            "p50_delta_ms": (int(p50 - base_p50) if (p50 is not None and base_p50 is not None) else None),
        }

    summary = {
        "generated_at_unix": int(time.time()),
        "zcode_version": (baseline.get("env_before") or {}).get("zcode_version"),
        "host": (baseline.get("env_before") or {}).get("date") and None,
        "baseline_lane": baseline["lane"],
        "note_timeouts": "timeout = runner-enforced 900s kill: its own failure class, never scored as model failure",
        "note_ambient": "zcode_cli_system_wide counts include the lane's own N processes plus unrelated concurrent swarm workers",
        "lanes": lanes,
    }
    summary.pop("host", None)

    out = args.out or os.path.join(args.results_dir, "summary.json")
    with open(out, "w") as fh:
        json.dump(summary, fh, indent=2)

    hdr = (f"{'lane':<5} {'n':>3} {'done':>4} {'t/o':>4} {'miss':>4} "
           f"{'s1':>6} {'s2':>6} {'s3':>6} {'s4':>6} {'s5':>6} "
           f"{'p50':>9} {'p95':>9} {'max':>9} {'p50xbase':>9} {'zcli avg/max':>12}")
    print(hdr)
    print("-" * len(hdr))
    for lane in lanes:
        lat = lane["latency_ms_completed_only"]
        spc = lane["subtask_pass_counts"]
        ratio = lane["vs_baseline"]["p50_ratio"]
        zc = lane["zcode_cli_system_wide"]
        zc_str = "-" if zc["mean"] is None else f"{zc['mean']}/{zc['max']}"
        def rate(s):
            return f"{spc[s]}/{lane['runs']}"
        print(
            f"{lane['lane']:<5} {lane['runs']:>3} {lane['completed']:>4} {lane['timeouts']:>4} {lane['missing']:>4} "
            f"{rate('s1'):>6} {rate('s2'):>6} {rate('s3'):>6} {rate('s4'):>6} {rate('s5'):>6} "
            f"{fmt_ms(lat['p50']):>9} {fmt_ms(lat['p95']):>9} {fmt_ms(lat['max']):>9} "
            f"{(f'{ratio:.2f}' if ratio is not None else '-'):>9} "
            f"{zc_str:>12}"
        )
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
