# Using rvsched

## Install

```bash
pip install rvsched
rvsched -h            # every command also has -h, with examples
```

Python 3.10+. No other dependencies.

## 1. Route

Give it every file your design needs. It prints one decision per module.

```bash
rvsched route examples/sample_design.v examples/sample_arithmetic.v
```

```json
[
  {
    "module": "riscv_decoder_unit",
    "fingerprint": "sha256:079db4c7...",
    "decision": { "action": "RUN", "engine": "FORMAL",
                  "reason": "Control-dominated, 16 state bits, no nonlinear arithmetic." },
    "prediction": { "engine": "FORMAL", "confidence": 0.92 }
  },
  {
    "module": "riscv_alu_multiplier",
    "decision": { "action": "RUN", "engine": "SIMULATION",
                  "reason": "2 nonlinear op(s) (var*var / div / mod) with operands up to 32 bits. ..." }
  }
]
```

| action | meaning |
|---|---|
| `RUN` | run it on `engine`: `FORMAL`, `SIMULATION` or `HYBRID_SPLIT` (formal the control, simulate the datapath) |
| `SKIP` | this exact structure was already proved; `evidence` links to the proof |
| `KNOWN_FAIL` | this exact structure already failed formal; fix the design before rerunning |

Add `--metrics` to see the numbers behind each verdict (state bits, nonlinear ops, operand widths, submodules).

## 2. Record what really happened

After your tool runs, write the outcome down:

```bash
rvsched record examples/sample_design.v --module riscv_decoder_unit \
    --engine FORMAL --status proved --seconds 3.1 --evidence https://ci.example/run/1
```

The next `route` of the same structure says:

```json
{ "action": "SKIP", "engine": "FORMAL",
  "reason": "this exact structure was already proved", "evidence": "https://ci.example/run/1" }
```

This also holds for a copy with every signal and module renamed, in any repo that reads the same store.

| status | later routes |
|---|---|
| `proved` | `SKIP` |
| `failed` | `KNOWN_FAIL` |
| `timeout` | send to `SIMULATION`, even if the prediction said `FORMAL` |
| `unknown` | ignored |

## 3. Calibrate

```bash
rvsched calibrate
```

```json
{ "records_with_outcome": 1, "misses": 0, "miss_rate": 0.0,
  "pairs": { "FORMAL -> FORMAL:proved": 1 }, "miss_detail": [] }
```

A miss is a prediction that reality contradicted. `miss_detail` shows the metrics of each one, so you can tune the thresholds at the top of `rvsched/verilog.py`.

## Sharing results

The store is a plain folder, `.rvsched/` by default. Commit it. Anyone can then read it with no server:

```bash
rvsched route rtl/*.v --store https://raw.githubusercontent.com/you/repo/main/.rvsched
```

URL stores are read-only; record locally and commit.

## In GitHub Actions

```yaml
- uses: 0x-auth/rv-verification-scheduler@v0.1.1
  with:
    files: rtl/*.v rtl/*.sv
    defines: FORMAL        # optional
```

It prints a one-line plan per module and leaves the full JSON in `rvsched-plan.json`.

A typical flow: route, run formal only on `RUN`/`FORMAL` modules, record each result, commit `.rvsched/`.

## Preprocessor defines

If your flow passes `-D` flags, pass the same ones. They change the design without changing the text, so they are folded into the fingerprint:

```bash
rvsched route top.v -D FORMAL -D SYNTH
```

## From Python

```python
from rvsched import get_language, open_store, resolve, record, decide, Outcome

v = get_language("verilog")
units = dict(v.split(open("fifo.v").read()))
fp = v.fingerprint(units)["fifo"]          # None if it depends on unseen files
pred = v.recognize(units["fifo"], units)
st = open_store(".rvsched")
print(decide(pred, resolve(fp, st)))
record(fp, "fifo", pred, Outcome("FORMAL", "proved", 3.1, "ci://run/1"), st)
```

## Exit codes

| code | meaning |
|---|---|
| 0 | ok |
| 2 | bad input (missing file, unknown module, bad store) |
| 3 | `record` refused: the module's fingerprint is unstable (pass the files it depends on) |

## When a module gets no fingerprint

`"fingerprint": null` means the module uses something not in the files you gave: an unknown submodule, a package, an undefined macro, an `include`. It is still routed, but never cached. Pass the missing files to fix it.

## Extending

See [ARCHITECTURE.md](ARCHITECTURE.md#extending): new languages and stores are plugins and need no change to rvsched.
