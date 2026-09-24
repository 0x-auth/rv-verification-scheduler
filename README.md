# RV Verification Scheduler

A static pre-compile linter for RISC-V RTL that decides, per module, whether a
block should go to a **formal** engine or to **simulation** — *before* you spend
CI time discovering that a formal proof will never converge.

## Why

Formal verification gives complete, mathematical coverage — but only on blocks
whose reachable state stays tractable. Two things reliably break it:

1. **Nonlinear arithmetic** — a variable-times-variable multiply, divide, or
   modulo. These are the classic model-checker killers. (A shift, or a multiply
   by a constant / power of two, is cheap and does *not* break formal.)
2. **Large sequential state** — reachable-state size grows roughly `2^bits`, so
   past some width of flip-flop state, unbounded proofs stop closing.

The usual failure mode is to point a formal tool at an ALU or a wide datapath,
watch it run for hours, and hit a memory-timeout — CI compute burned to learn
something a two-second static pass could have told you. This tool is that pass.
Control-dominated logic → formal (full coverage). Wide/nonlinear datapath →
simulation (or bounded/BMC). Mixed → a hybrid split.

## What it measures

`parse_core.py` statically extracts, per module:

| Signal | What it means | Why it matters |
|---|---|---|
| `sequential_state_bits` | width-weighted flop state (`reg [63:0]` = 64, not 1) | reachability / BDD cost scales with state bits |
| `nonlinear_arith_ops` | `var*var`, `/`, `%` (constant/shift excluded) | the dominant cause of formal blow-up |
| `max_datapath_width` | widest declared signal | wide nonlinear ops are worse |
| `control_ops` | `always`, `if`, `case`, … | control logic is formal-friendly |
| `rvvi_hooks` | RVVI / RVFI interface traces | these are what you formally check |
| `sva_assertions` | `assert`/`assume`/`cover property` | explicit formal targets |

Note: this is a static estimate from source, not full elaboration. It is
deliberately cheap (regex-grade) so it can run in the pre-compile phase. It
trades exactness for speed — see *Limitations*.

## How routing works

`ttc` reads the metrics and routes with the most decisive signal first:

1. nonlinear arithmetic on a wide datapath → **SIMULATION**
2. narrow nonlinear arithmetic → **HYBRID** (bounded formal / BMC viable)
3. sequential state beyond the proof budget → **SIMULATION**
4. RVVI/RVFI or assertions present → **FORMAL** (that's the point of them)
5. control-dominated, bounded state, no nonlinear arithmetic → **FORMAL**
6. otherwise → **HYBRID_SPLIT**

The thresholds (`WIDE_MULT_BITS`, `STATE_BITS_HARD`, `STATE_BITS_SOFT` at the
top of `ttc`) are ordinary engineering starting points, meant to be **calibrated
against real tool behaviour** — not universal constants. Tune them to your
formal tool and core.

## Quick start

```bash
# whole workspace
./test_pipeline_harness.sh

# single module
python3 parse_core.py sample_arithmetic.v | python3 ttc
```

Example — a 32×32 multiplier is correctly sent to simulation, with the reason:

```json
{
  "target_module": "riscv_alu_multiplier",
  "recommended_engine": "SIMULATION",
  "confidence": 0.97,
  "reasoning": "2 nonlinear op(s) (var*var / div / mod) on datapath up to 64 bits wide. Unbounded formal proof will not converge; route to simulation (or bounded/BMC).",
  "metrics_evaluated": { "nonlinear_arith_ops": 2, "nonlinear_detail": ["op_a * op_b", "op_a / op_b"], "sequential_state_bits": 64, "max_datapath_width": 64 }
}
```

## Limitations (honest)

- Static source estimate, not elaboration: it does not build the real cone of
  logic. Combinational `logic` may be counted as state, which over-estimates;
  declarations spread over multiple lines may be missed, which under-estimates.
  Under-estimating is the unsafe direction here — it routes an intractable
  module to FORMAL and burns the CI time this pass exists to save — so treat a
  near-threshold result as a reason to check the module by hand.
  `sample_multi_decl.v` is the regression fixture for this (72 state bits; an
  earlier version reported 56).
- Thresholds are uncalibrated defaults. They should be fit to real runs.
- Macro-heavy or generate-heavy code is not expanded.

## Roadmap

The next real step is calibration: run these predictions against what an actual
open-source formal flow (e.g. Yosys + SymbiYosys, or the `riscv-formal` /
RVFI framework) *actually does* — converge vs. timeout — on real open cores
(Ibex, PicoRV32, VexRiscv), and report the prediction accuracy. That turns a
heuristic router into a measured one.

## Layout

```
parse_core.py             # static RTL metric extractor
ttc                       # verification-track classifier
test_pipeline_harness.sh  # batch wrapper over the workspace
sample_*.v / *.sv         # test fixtures (control, arithmetic, RVVI, mixed, multi-decl)
```

## License

Apache 2.0 — see `LICENSE`.
