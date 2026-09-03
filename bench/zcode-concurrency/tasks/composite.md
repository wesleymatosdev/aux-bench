# Composite micro-benchmark task

Work ONLY in the current directory. Complete all five sub-tasks below, then stop. Do not create, modify, or delete any files other than the five named here. No commentary needed in your final message.

- **S1**: Create `f1.txt` containing exactly `zcode-bench-2026` — one line, no other characters (a single trailing newline is acceptable).
- **S2**: Create `f2.txt` containing exactly the decimal value of `128*64+7` — one line, no other characters (a single trailing newline is acceptable).
- **S3**: Create `f3.py` defining a function `rotl(n, b)` that computes a 32-bit left rotate: `((n << b) | (n >> (32 - b))) & 0xFFFFFFFF`. Include an `if __name__ == "__main__":` block whose only action is `print(rotl(0xC0FFEE00, 8))`.
- **S4**: The file `in.json` in the current directory is invalid JSON (it has trailing commas). Create `out.json` containing the same data as `in.json`, as valid JSON, preserving every key and value exactly. Do not modify `in.json`.
- **S5**: Create `manifest.txt` listing exactly the filenames you created — `f1.txt`, `f2.txt`, `f3.py`, `out.json` — one per line, sorted alphabetically, with no other lines.
