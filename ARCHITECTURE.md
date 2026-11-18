# Architecture

rvsched is a protocol with one implementation: three verbs, one record format, and plugins for everything that varies.

```
 RTL files ──► split ──► units {name: source}
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
       fingerprint                    recognize
   (structure → hash)           (source → predicted engine)
            │                             │
            ▼                             │
   resolve(fp, store) ──► record? ───────►┤
                                          ▼
                                decide(prediction, record)
                                          │
                       SKIP · KNOWN_FAIL · RUN <engine>
                                          │
                     your tool runs ──► record(fp, prediction, outcome)
```

## The core (`rvsched/core.py`)

Frozen. Adding languages or stores never touches it.

| verb | does | cost |
|---|---|---|
| `recognize(source)` | predicts which class the module is in | one regex pass, no solving |
| `resolve(fingerprint)` | returns the last record for this exact structure, or `None` ("the void") | one file read or HTTP GET |
| `record(fp, prediction, outcome)` | appends what a real tool did | one line appended |

`decide(prediction, record)` combines them. **Recorded truth beats prediction:**

| recorded outcome | decision |
|---|---|
| FORMAL proved | `SKIP` (with evidence) |
| FORMAL failed | `KNOWN_FAIL` |
| FORMAL timeout | `RUN SIMULATION` |
| none / unknown | `RUN <predicted engine>` |

This is where the learning happens. It lives in the store, not in model weights, so every decision can be read and traced to its evidence.

## The record (`rvsched/1`)

```json
{
  "schema": "rvsched/1",
  "fingerprint": "sha256:…",
  "module": "fifo",
  "prediction": { "engine": "FORMAL", "confidence": 0.92, "reason": "…",
                  "recognizer": "verilog/static-v1", "metrics": { … } },
  "outcome": { "engine": "FORMAL", "status": "proved", "seconds": 3.1, "evidence": "https://…" },
  "created": 1763300000.0,
  "miss": false
}
```

A miss is a prediction contradicted by reality: FORMAL predicted but formal timed out, or SIMULATION predicted but formal finished. `HYBRID_SPLIT` hedges, so it never counts as a miss.

## Recognition (`rvsched/verilog.py`)

The question is not "solve it" but "which class is it in", answered before any search. Signals, most decisive first:

1. **Nonlinear arithmetic.** A variable × variable multiply, divide or modulo with operands wider than `WIDE_MULT_BITS` (8) leads to `SIMULATION`. Narrower ones lead to `HYBRID_SPLIT`. A constant or parameter operand counts as cheap.
2. **State.** Flip-flop bits are weighted by width. `reg [7:0] a, b, c` counts 24 bits, and memory arrays count every word. Above `STATE_BITS_HARD` (64) leads to `SIMULATION`.
3. **Hooks.** RVFI/RVVI signals or SVA properties lead to `FORMAL`.
4. **Small and control-heavy** (≤ `STATE_BITS_SOFT`, 24 bits) leads to `FORMAL`. Anything else is `HYBRID_SPLIT`.

Submodule state and arithmetic are added to their parent, so a wrapper around a CPU is judged as a CPU. Widths written with parameters (`[W-1:0]`) are resolved. A width that can't be resolved counts as 32 bits, because undercounting is the unsafe direction.

## Fingerprint

The goal: the same hash for the same structure, whatever it is named.

1. Strip comments. Tokenize, so whitespace is irrelevant.
2. Rename every name the unit **declares** (ports, signals, parameters, typedefs, instances, labels) to `v0, v1, …` in order of first use.
3. Replace every reference to another unit in the input (submodule, interface, package, `define macro) with **that unit's fingerprint**. This makes a Merkle tree: change a child and every parent changes.
4. Keep member and port names after `.` literally; they are fixed by the child's hash.
5. If anything else is referenced (an unknown module, a package not given, an undefined macro), the fingerprint is `None`. Such a module is never cached, only recognized. Errors go in the safe direction: a missed reuse, never a false one.
6. `-D` defines are hashed in, because they change the design without changing the text.

## Stores (`rvsched/stores.py`)

The store holds addresses (verdicts and evidence links), never designs or proofs. This is the empty-center pattern from `0x-auth/void`: route to an answer that lives elsewhere.

```
<root>/<first 2 hex>/<hex>.jsonl      one JSON record per line, append-only
```

The layout is identical on disk and over HTTP, so a committed directory is readable from its raw URL.

- `DirStore` reads and writes. Each append is a single small write.
- `HttpStore` (`https://…`) is read-only. A 404 means the void.

## Extending

Plugins register through Python entry points; rvsched loads them at startup.

```toml
[project.entry-points."rvsched.languages"]
vhdl = "my_pkg.vhdl"

[project.entry-points."rvsched.stores"]
s3 = "my_pkg.s3store"
```

A **language** registers with `@rvsched.language("vhdl")` and provides:

```python
split(text) -> [(name, source), ...]
recognize(source, units=None) -> Verdict
fingerprint(units: dict) -> {name: "sha256:..." | None}
```

A **store** registers with `@rvsched.store("s3")`, takes its location string, and provides `get(fp)`, `put(record)`, `all()`.

## Files

| path | role |
|---|---|
| `rvsched/core.py` | verbs, record schema, `decide`, plugin registry |
| `rvsched/verilog.py` | Verilog/SV plugin: split, recognize, fingerprint, thresholds |
| `rvsched/stores.py` | directory store and read-only URL store |
| `rvsched/cli.py` | `rvsched route / record / calibrate` |
| `action.yml` | GitHub Action |
| `bench/run.py` | benchmark against Yosys equivalence checking |
| `parse_core.py`, `ttc` | the original pipeline, kept as thin wrappers |

## Release

Bump `__version__` in `rvsched/__init__.py` (the only place it is set), then push to `main`. The release workflow publishes to PyPI if that version isn't there yet and tags it `vX.Y.Z`. The PyPI page is this repo's README.
