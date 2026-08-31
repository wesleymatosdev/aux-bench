//! aux-bench — benchmark local Ollama models for Hermes auxiliary task slots.
//!
//! Auxiliary slots (title_generation, compression, curator, ...) need a small,
//! fast, obedient model. The failure mode that matters most is not "wrong
//! answer" but "thinking model leaks chain-of-thought into content and returns
//! nothing usable". This harness scores exactly that.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

const DEFAULT_HOST: &str = "http://127.0.0.1:11434";

#[derive(Debug, Deserialize)]
struct Suite {
    task: String,
    #[serde(default)]
    description: String,
    system: String,
    #[serde(default)]
    options: Value,
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    user: String,
    #[serde(default)]
    max_words: Option<usize>,
    #[serde(default)]
    forbid_substrings: Vec<String>,
    #[serde(default)]
    expect_any: Vec<String>,
}

#[derive(Debug, Serialize, Clone)]
struct CaseResult {
    case: String,
    output: String,
    latency_ms: u128,
    passed: bool,
    failures: Vec<String>,
    empty_content: bool,
    leaked_reasoning: bool,
}

#[derive(Debug, Serialize, Clone)]
struct ModelResult {
    model: String,
    task: String,
    pass_rate: f64,
    passed: usize,
    total: usize,
    median_latency_ms: u128,
    mean_latency_ms: u128,
    empty_content_count: usize,
    leaked_reasoning_count: usize,
    error: Option<String>,
    cases: Vec<CaseResult>,
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "-h" || a == "--help") {
        print_help();
        return;
    }

    let mut suite_path: Option<PathBuf> = None;
    let mut models: Vec<String> = Vec::new();
    let mut host = std::env::var("OLLAMA_HOST").unwrap_or_else(|_| DEFAULT_HOST.to_string());
    let mut out: Option<PathBuf> = None;
    let mut timeout_s: u64 = 300;
    let mut keep_alive = "5m".to_string();

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--suite" => {
                i += 1;
                suite_path = args.get(i).map(PathBuf::from);
            }
            "--models" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    models = v
                        .split(',')
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect();
                }
            }
            "--host" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    host = v.clone();
                }
            }
            "--out" => {
                i += 1;
                out = args.get(i).map(PathBuf::from);
            }
            "--timeout" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    timeout_s = v.parse().unwrap_or(300);
                }
            }
            "--keep-alive" => {
                i += 1;
                if let Some(v) = args.get(i) {
                    keep_alive = v.clone();
                }
            }
            other => {
                eprintln!("unknown argument: {other}");
                print_help();
                std::process::exit(2);
            }
        }
        i += 1;
    }

    let suite_path = match suite_path {
        Some(p) => p,
        None => {
            eprintln!("error: --suite is required");
            print_help();
            std::process::exit(2);
        }
    };

    let suite: Suite = match load_suite(&suite_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error: failed to load suite {}: {e}", suite_path.display());
            std::process::exit(1);
        }
    };

    if models.is_empty() {
        models = match discover_local_models(&host, timeout_s) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("error: could not list models from {host}: {e}");
                std::process::exit(1);
            }
        };
    }

    if models.is_empty() {
        eprintln!("error: no candidate models (all cloud-tagged or none installed)");
        std::process::exit(1);
    }

    eprintln!("suite: {} ({} cases)", suite.task, suite.cases.len());
    if !suite.description.is_empty() {
        eprintln!("       {}", suite.description);
    }
    eprintln!("host:  {host}");
    eprintln!("models ({}): {}", models.len(), models.join(", "));
    eprintln!();

    let mut results: Vec<ModelResult> = Vec::new();
    for model in &models {
        eprintln!("== {model}");
        let r = run_model(&host, model, &suite, timeout_s, &keep_alive);
        for c in &r.cases {
            let mark = if c.passed { "pass" } else { "FAIL" };
            eprintln!(
                "   {:<22} {} {:>6}ms  {}",
                c.case,
                mark,
                c.latency_ms,
                one_line(&c.output, 60)
            );
            if !c.passed {
                eprintln!("      -> {}", c.failures.join("; "));
            }
        }
        eprintln!(
            "   pass {}/{}  median {}ms\n",
            r.passed, r.total, r.median_latency_ms
        );
        // Free VRAM between models: large local models cannot be co-resident.
        unload(&host, model, timeout_s);
        results.push(r);
    }

    print_table(&suite.task, &mut results);

    if let Some(path) = out {
        let payload = json!({
            "task": suite.task,
            "host": host,
            "generated_at_unix": std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0),
            "results": results,
        });
        match serde_json::to_string_pretty(&payload)
            .map_err(|e| e.to_string())
            .and_then(|s| fs::write(&path, s).map_err(|e| e.to_string()))
        {
            Ok(_) => eprintln!("\nwrote {}", path.display()),
            Err(e) => eprintln!("\nfailed to write {}: {e}", path.display()),
        }
    }
}

fn print_help() {
    eprintln!(
        "aux-bench — benchmark local models for Hermes auxiliary slots

USAGE:
  aux-bench --suite <file.json> [--models a,b,c] [--host URL] [--out results.json]
            [--timeout SECS] [--keep-alive DUR]

  --suite       Suite JSON describing the auxiliary task and its cases (required).
  --models      Comma-separated model tags. Default: all local (non-:cloud, non-embed) models.
  --host        Ollama base URL. Default $OLLAMA_HOST or {DEFAULT_HOST}.
  --out         Write full per-case results as JSON.
  --timeout     Per-request timeout in seconds. Default 300.
  --keep-alive  Ollama keep_alive for each request. Default \"0\" (unload right after)."
    );
}

fn load_suite(path: &Path) -> Result<Suite, String> {
    let raw = fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&raw).map_err(|e| e.to_string())
}

/// Local models only: `:cloud` tags are remote and embedding models cannot chat.
fn discover_local_models(host: &str, timeout_s: u64) -> Result<Vec<String>, String> {
    let url = format!("{host}/api/tags");
    let body: Value = agent(timeout_s)
        .get(&url)
        .call()
        .map_err(|e| e.to_string())?
        .body_mut()
        .read_json()
        .map_err(|e| e.to_string())?;

    let mut out = Vec::new();
    if let Some(arr) = body.get("models").and_then(|m| m.as_array()) {
        for m in arr {
            if let Some(name) = m.get("name").and_then(|n| n.as_str()) {
                if name.contains(":cloud") || name.contains("embed") {
                    continue;
                }
                out.push(name.to_string());
            }
        }
    }
    Ok(out)
}

fn agent(timeout_s: u64) -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(timeout_s)))
        .build()
        .into()
}

fn run_model(
    host: &str,
    model: &str,
    suite: &Suite,
    timeout_s: u64,
    keep_alive: &str,
) -> ModelResult {
    let mut cases = Vec::new();
    let mut latencies: Vec<u128> = Vec::new();
    let mut hard_error: Option<String> = None;

    // Warm-up: load weights into RAM so the first scored case measures
    // generation, not a multi-GB cold load off disk.
    let _ = chat(
        host,
        model,
        "Reply with OK.",
        "ping",
        &suite.options,
        timeout_s,
        keep_alive,
    );

    for case in &suite.cases {
        let started = Instant::now();
        let resp = chat(
            host,
            model,
            &suite.system,
            &case.user,
            &suite.options,
            timeout_s,
            keep_alive,
        );
        let latency_ms = started.elapsed().as_millis();

        match resp {
            Ok((content, reasoning)) => {
                let (passed, failures, empty, leaked) = score(&content, &reasoning, case);
                latencies.push(latency_ms);
                cases.push(CaseResult {
                    case: case.name.clone(),
                    output: content,
                    latency_ms,
                    passed,
                    failures,
                    empty_content: empty,
                    leaked_reasoning: leaked,
                });
            }
            Err(e) => {
                if hard_error.is_none() {
                    hard_error = Some(e.clone());
                }
                cases.push(CaseResult {
                    case: case.name.clone(),
                    output: String::new(),
                    latency_ms,
                    passed: false,
                    failures: vec![format!("request error: {e}")],
                    empty_content: true,
                    leaked_reasoning: false,
                });
            }
        }
    }

    let passed = cases.iter().filter(|c| c.passed).count();
    let total = cases.len();
    ModelResult {
        model: model.to_string(),
        task: suite.task.clone(),
        pass_rate: if total == 0 {
            0.0
        } else {
            passed as f64 / total as f64
        },
        passed,
        total,
        median_latency_ms: median(&mut latencies.clone()),
        mean_latency_ms: if latencies.is_empty() {
            0
        } else {
            latencies.iter().sum::<u128>() / latencies.len() as u128
        },
        empty_content_count: cases.iter().filter(|c| c.empty_content).count(),
        leaked_reasoning_count: cases.iter().filter(|c| c.leaked_reasoning).count(),
        error: hard_error,
        cases,
    }
}

/// Returns (content, reasoning). Ollama's native /api/chat keeps thinking in a
/// separate `thinking` field when the model honours think:false; models that
/// ignore it dump chain-of-thought straight into content.
fn chat(
    host: &str,
    model: &str,
    system: &str,
    user: &str,
    options: &Value,
    timeout_s: u64,
    keep_alive: &str,
) -> Result<(String, String), String> {
    let url = format!("{host}/api/chat");
    let mut payload = json!({
        "model": model,
        "messages": [
            { "role": "system", "content": system },
            { "role": "user", "content": user }
        ],
        "stream": false,
        "think": false,
        "keep_alive": keep_alive,
    });
    if !options.is_null() {
        payload["options"] = options.clone();
    }

    let mut resp = agent(timeout_s)
        .post(&url)
        .send_json(payload)
        .map_err(|e| e.to_string())?;

    let body: Value = resp.body_mut().read_json().map_err(|e| e.to_string())?;
    if let Some(err) = body.get("error").and_then(|e| e.as_str()) {
        return Err(err.to_string());
    }

    let msg = body.get("message").cloned().unwrap_or(Value::Null);
    let content = msg
        .get("content")
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let reasoning = msg
        .get("thinking")
        .or_else(|| msg.get("reasoning"))
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    Ok((content, reasoning))
}

/// (passed, failures, empty_content, leaked_reasoning)
fn score(content: &str, reasoning: &str, case: &Case) -> (bool, Vec<String>, bool, bool) {
    let mut failures = Vec::new();
    let trimmed = content.trim();

    let empty = trimmed.is_empty();
    if empty {
        if !reasoning.is_empty() {
            failures.push("empty content, model returned only reasoning".to_string());
        } else {
            failures.push("empty content".to_string());
        }
    }

    let lower = trimmed.to_lowercase();
    let mut leaked = false;
    for needle in &case.forbid_substrings {
        if lower.contains(&needle.to_lowercase()) {
            leaked = true;
            failures.push(format!("contains forbidden {needle:?}"));
        }
    }

    if let Some(max) = case.max_words {
        let words = trimmed.split_whitespace().count();
        if !empty && words > max {
            failures.push(format!("{words} words > max {max}"));
        }
    }

    if !case.expect_any.is_empty() && !empty {
        let hit = case
            .expect_any
            .iter()
            .any(|k| lower.contains(&k.to_lowercase()));
        if !hit {
            failures.push(format!("none of {:?} present", case.expect_any));
        }
    }

    (failures.is_empty(), failures, empty, leaked)
}

fn unload(host: &str, model: &str, timeout_s: u64) {
    let url = format!("{host}/api/generate");
    let _ = agent(timeout_s)
        .post(&url)
        .send_json(json!({ "model": model, "keep_alive": 0 }));
}

fn median(v: &mut Vec<u128>) -> u128 {
    if v.is_empty() {
        return 0;
    }
    v.sort_unstable();
    let mid = v.len() / 2;
    if v.len() % 2 == 0 {
        (v[mid - 1] + v[mid]) / 2
    } else {
        v[mid]
    }
}

fn one_line(s: &str, max: usize) -> String {
    let flat: String = s.chars().map(|c| if c == '\n' { '⏎' } else { c }).collect();
    if flat.chars().count() > max {
        let head: String = flat.chars().take(max).collect();
        format!("{head}…")
    } else {
        flat
    }
}

fn print_table(task: &str, results: &mut Vec<ModelResult>) {
    results.sort_by(|a, b| {
        b.pass_rate
            .partial_cmp(&a.pass_rate)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.median_latency_ms.cmp(&b.median_latency_ms))
    });

    println!();
    println!("RESULTS — {task}");
    println!(
        "{:<48} {:>6} {:>9} {:>9} {:>7} {:>7}",
        "model", "pass", "median", "mean", "empty", "leak"
    );
    println!("{}", "-".repeat(92));
    for r in results.iter() {
        println!(
            "{:<48} {:>5}/{:<1} {:>8}ms {:>8}ms {:>7} {:>7}",
            r.model,
            r.passed,
            r.total,
            r.median_latency_ms,
            r.mean_latency_ms,
            r.empty_content_count,
            r.leaked_reasoning_count
        );
    }

    let mut viable: Vec<&ModelResult> = results.iter().filter(|r| r.pass_rate >= 1.0).collect();
    viable.sort_by_key(|r| r.median_latency_ms);
    println!();
    match viable.first() {
        Some(w) => println!(
            "WINNER: {} — {}/{} cases, {}ms median",
            w.model, w.passed, w.total, w.median_latency_ms
        ),
        None => {
            let best = results.first();
            match best {
                Some(b) if b.passed > 0 => println!(
                    "NO CLEAN WINNER — best is {} at {}/{}; do not wire a partial pass into a live slot",
                    b.model, b.passed, b.total
                ),
                _ => println!("NO VIABLE LOCAL MODEL — every candidate failed every case"),
            }
        }
    }

    let mut by_error: BTreeMap<&str, usize> = BTreeMap::new();
    for r in results.iter() {
        if let Some(e) = &r.error {
            *by_error.entry(e.as_str()).or_insert(0) += 1;
        }
    }
    if !by_error.is_empty() {
        println!("\nrequest errors:");
        for (e, n) in by_error {
            println!("  {n}x {e}");
        }
    }
}
