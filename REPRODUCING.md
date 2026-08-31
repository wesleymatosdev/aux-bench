# Reproducing these benchmarks

Everything here runs on your own machine against open-weight models. No API
keys, no accounts, no cloud spend. Total setup is three commands plus a model
download.

The results in `results/` were produced exactly this way, on an M4 Max
(48 GB unified memory), macOS 26.4.

## 1. Install a runtime

aux-bench speaks two protocols, so you can use either runtime. Pick one.

### Option A: Kronk (recommended — Go, llama.cpp, no Python)

[Kronk](https://github.com/ardanlabs/kronk) is a Go model server over
llama.cpp with an OpenAI-compatible API. It downloads its own native libraries
on first run.

```shell
# macOS/Linux via Homebrew
brew install ardanlabs/kronk/kronk

# or via Go (any platform)
go install github.com/ardanlabs/kronk/cmd/kronk@latest

kronk server start          # serves OpenAI-compatible API on :11435
```

Pull the models (each is a HuggingFace GGUF repo):

```shell
kronk model pull ornith-ai/Ornith-1.5-9B-GGUF:Q4_K_M --local
kronk model pull unsloth/GLM-5.3-Flash-GGUF:UD-Q2_K_XL --local
kronk model list
```

### Option B: Ollama

```shell
ollama pull gemma4:26b
ollama serve                # serves native API on :11434
```

## 2. Build aux-bench

```shell
cargo build --release
```

Rust only — no Python, no virtualenv, no lockfile drift.

## 3. Run a suite

```shell
# against Kronk (OpenAI-compatible)
./target/release/aux-bench \
    --suite suites/title_generation.json \
    --api openai \
    --out results/my-run.json

# against Ollama (native API, auto-discovers installed models)
./target/release/aux-bench \
    --suite suites/title_generation.json \
    --out results/my-run.json
```

Omit `--models` to benchmark every model the server reports. Pass
`--models a,b` to pin an exact list.

## Getting numbers you can trust

Latency here is wall time against a shared server, so it measures whatever
your machine is doing. Two runs of the same models differed by ~90x purely
from contention (see the README section on this). Before recording a result:

1. **Idle the machine.** Check nothing else is resident:
   `ollama ps` or `kronk model ps`. Close other model-serving processes.
2. **Run each model sequentially.** aux-bench already unloads between
   candidates on Ollama; large models cannot be co-resident in RAM.
3. **Swap the order and re-run.** `--models a,b` then `--models b,a`. If the
   ranking flips, the difference is noise — report them as tied.
4. **Trust pass rate over latency.** Pass/fail is deterministic and
   machine-independent; latency is not.

Each result JSON records the `api`, `host`, and `generated_at_unix` that
produced it, so a committed result is self-describing.

## Hardware differences

Absolute latency will not match ours — it depends on your memory bandwidth,
quantization, and runtime. What *should* reproduce is the pass/fail column:
whether a model can follow a short instruction without leaking its
chain-of-thought is a property of the model, not your hardware.

If a model passes for us and fails for you, check your quantization first: a
heavily quantized build of the same model can lose instruction-following that
the higher-precision build has.
