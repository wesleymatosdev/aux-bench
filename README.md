# aux-bench

Benchmark local Ollama models for Hermes **auxiliary task slots**
(`title_generation`, `compression`, `curator`, `mcp`, `web_extract`, ...).

Auxiliary slots don't need a frontier model — they need a small, fast, *obedient*
one. The failure mode that actually bites is not "wrong answer", it's:

> a reasoning model ignores `think:false`, spends its whole token budget on
> chain-of-thought, and returns **empty content**.

That's a silent failure. The slot looks configured, the model exists, and Hermes
gets nothing back. aux-bench scores exactly that, so you pick a model on measured
behavior instead of vibes.

## Why this exists

`auxiliary.title_generation` was pinned to a model that 404'd. Every obvious
local replacement (qwen3:30b, gemma4:26b, qwen3-30b-64k) *looked* fine and was
in fact useless for the job — all three leaked reasoning into `content` and
returned an empty title. Discovering that by hand cost a dozen ad-hoc curl calls.
This harness turns that into one command, repeatable for every future slot.

## Usage

```
cargo build --release

# all local models (auto-discovered, :cloud and embedding models skipped)
./target/release/aux-bench --suite suites/title_generation.json --out results/title_generation.json

# specific candidates
./target/release/aux-bench --suite suites/title_generation.json \
    --models gemma4:26b,muse-glimmer:latest
```

Flags:

| flag | meaning |
|---|---|
| `--suite` | suite JSON describing the task and its cases (required) |
| `--models` | comma-separated tags; default = all local models |
| `--host` | Ollama base URL (default `$OLLAMA_HOST` or `http://127.0.0.1:11434`) |
| `--out` | write full per-case results as JSON |
| `--timeout` | per-request timeout in seconds (default 300) |
| `--keep-alive` | Ollama `keep_alive` per request (default `0`) |

Models are unloaded between candidates — large local models can't be co-resident
in RAM, so running them sequentially is not optional.

## Writing a suite

A suite is one auxiliary task. Each case asserts on the *content* field:

```json
{
  "task": "title_generation",
  "system": "You generate short conversation titles. Output ONLY the title...",
  "options": { "num_predict": 40, "temperature": 0.3 },
  "cases": [
    {
      "name": "classifier_handoff",
      "user": "resuming a classifier benchmark handoff",
      "max_words": 6,
      "forbid_substrings": ["Hmm", "the user wants", "Let me"],
      "expect_any": ["classifier", "benchmark", "handoff"]
    }
  ]
}
```

- `max_words` — catches models that write a paragraph instead of a title.
- `forbid_substrings` — catches leaked chain-of-thought.
- `expect_any` — at least one keyword must appear, so a fast model can't win by
  emitting confident nonsense.

Empty content always fails, and is reported separately in the `empty` column
because it's the dominant failure mode.

## Reading the output

```
model                              pass    median      mean   empty    leak
--------------------------------------------------------------------------
gemma4:26b                          6/6     900ms     950ms       0       0
qwen3:30b                           0/6    5100ms    5200ms       6       0
```

`empty` = returned nothing usable. `leak` = chain-of-thought in the answer.

A model is only declared WINNER at a **100% pass rate**, tie-broken by latency.
A partial pass prints `NO CLEAN WINNER` rather than a recommendation — a slot
that works 4 times out of 6 is a slot that fails silently in production.

## Adding a new slot

When a new auxiliary slot needs a model, write `suites/<slot>.json` with 5-6
representative cases and run the harness. Keep the suite in git: it's the
regression test for that slot, and re-runnable when models are updated.
