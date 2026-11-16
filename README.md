# rvsched

Before you run formal verification on an RTL module, ask two questions:

1. **Has this exact structure already been proved?** If so, skip it.
2. **If not, will formal finish, or should this go to simulation?**

`rvsched` answers both in about a second, without running any solver and without an AI model.

```bash
pip install rvsched
rvsched route rtl/*.v
```

```json
{ "module": "riscv_alu_multiplier",
  "decision": { "action": "RUN", "engine": "SIMULATION",
    "reason": "2 nonlinear op(s) with operands up to 32 bits. Unbounded formal will not converge." } }
```

## How it works

- **Recognize.** It reads the source and looks for what makes formal proofs blow up: variable × variable multiply, divide or modulo on wide operands, and large flip-flop state. It doesn't solve anything.
- **Fingerprint.** It hashes each module's *structure*. Renaming signals or modules, comments and whitespace don't change the hash; changing logic does. A parent's hash includes its children's hashes.
- **Remember.** After your tool runs, you record what happened. Next time the same structure appears, in this repo or a renamed copy anywhere else, the recorded result is used directly.

```bash
rvsched record rtl/*.v --module fifo --engine FORMAL --status proved --evidence https://ci/run/42
rvsched route rtl/*.v          # fifo -> SKIP, already proved
rvsched calibrate              # how often the predictions were wrong
```

Recorded outcomes override predictions. If formal timed out on a structure once, that structure goes to simulation from then on. Every verdict says why, and every skip points to its evidence.

## Share results

The store is a plain folder (`.rvsched/`). Commit it, and anyone can read it from its raw URL without installing a server:

```bash
rvsched route rtl/*.v --store https://raw.githubusercontent.com/you/repo/main/.rvsched
```

## In CI

```yaml
- uses: 0x-auth/rv-verification-scheduler@v0.1.0
  with:
    files: rtl/*.v
```

## Measured

`bench/run.py` gives each module to a real formal tool (Yosys equivalence checking: RTL against its own synthesized netlist, 60 s limit) and compares the outcome with the prediction made beforehand. The run covered 28 modules: PicoRV32, the examples, and small probe modules written for this test.

| | |
|---|---|
| scored | 25 (3 PicoRV32 wrappers predicted correctly but can't be cached, see below) |
| wrong | 2: `counter_128` and `picorv32_pcpi_mul`, sent to simulation but formal proved them |
| multipliers | 8-bit operands proved, 10-bit and wider did not |

**Read honestly.** The multiplier threshold was fixed using this same run, so those rows are not an independent test. This kind of check matches flip-flops by name, so it says little about the state-size rule; both misses come from that rule. A property-checking benchmark is the next test.

To reproduce (needs `yosys` or `pip install yowasp-yosys`): `python3 bench/run.py path/to/picorv32.v`, then `rvsched calibrate --store bench/.rvsched`.

## Limits

- It reads source; it doesn't elaborate the design. Unresolvable widths are assumed to be 32 bits, because guessing too high is the safe direction.
- A module that depends on something it can't see (an unknown module, a package, an undefined macro) gets no fingerprint. It is never cached, only recognized.
- If your flow uses `-D` defines, pass the same ones (`-D FORMAL`). They are folded into the fingerprint.
- Thresholds live at the top of `rvsched/verilog.py`. Tune them to your tool, or let `calibrate` show you where they're wrong.

## Extend it

The core (`rvsched/core.py`) is three functions and one record format, and it doesn't change. New languages and stores are plugins:

```toml
# your package's pyproject.toml
[project.entry-points."rvsched.languages"]
vhdl = "my_pkg.vhdl"          # registers itself with @rvsched.language("vhdl")

[project.entry-points."rvsched.stores"]
s3 = "my_pkg.s3store"         # registers itself with @rvsched.store("s3")
```

A language provides `split`, `recognize` and `fingerprint`. A store provides `get`, `put` and `all`. The record format is `rvsched/1`; see `Record` in `core.py`.

## License

Apache 2.0
