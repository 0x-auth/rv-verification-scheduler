#!/usr/bin/env python3
"""Does the router predict what a real formal tool does?

Task given to the tool, per module: prove the RTL equivalent to its own
synthesized gate netlist (the job an equivalence checker does). Yosys's own
flow: equiv_make, equiv_simple -seq 5, equiv_induct -seq 5, equiv_status
-assert. Built-in SAT solver, TIMEOUT seconds wall clock. ABC is skipped.

    proved within budget          -> FORMAL:proved
    unproven or out of time       -> FORMAL:timeout
    tool error                    -> unknown (not scored)

Predictions are written by `rvsched route` BEFORE any tool runs. Outcomes are
written with `rvsched record`, so `rvsched calibrate` reads the result.

    python3 bench/run.py path/to/picorv32.v      # extra RTL files optional
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
YOSYS = os.environ.get("YOSYS") or shutil.which("yosys") or shutil.which("yowasp-yosys")
TIMEOUT = int(os.environ.get("TIMEOUT", 60))
STORE = str(HERE / ".rvsched")


def probes() -> Path:
    """Small modules that isolate one property each. Written by us, labelled
    as such in the results."""
    d = HERE / "probes"
    d.mkdir(exist_ok=True)
    for w in (8, 16, 32, 64, 128):
        (d / f"counter_{w}.v").write_text(
            f"module counter_{w}(input wire clk, input wire rst, output reg [{w-1}:0] q);\n"
            f"  always @(posedge clk) if (rst) q <= 0; else q <= q + 1;\nendmodule\n")
    for n in (8, 16, 32, 48, 64):
        (d / f"shreg_{n}.v").write_text(
            f"module shreg_{n}(input wire clk, input wire d, output wire q);\n"
            f"  reg [{n-1}:0] s;\n  always @(posedge clk) s <= {{s[{n-2}:0], d}};\n"
            f"  assign q = s[{n-1}];\nendmodule\n")
    for w in (4, 6, 8, 10, 12, 16):
        (d / f"mul_{w}.v").write_text(
            f"module mul_{w}(input wire clk, input wire [{w-1}:0] a, input wire [{w-1}:0] b,\n"
            f"  output reg [{2*w-1}:0] p);\n  always @(posedge clk) p <= a * b;\nendmodule\n")
    (d / "cmul_32.v").write_text(
        "module cmul_32(input wire clk, input wire [31:0] a, output reg [31:0] p);\n"
        "  always @(posedge clk) p <= a * 32'd5;\nendmodule\n")
    return d


def prove(files, top):
    reads = "; ".join(f"read_verilog -sv {f}" for f in files)
    script = f"""
{reads}
hierarchy -top {top}; proc; memory; flatten; async2sync; opt_clean; rename {top} gold; design -stash gold
{reads}
hierarchy -top {top}; synth -flatten -noabc -top {top}; async2sync; rename {top} gate; design -stash gate
design -copy-from gold -as gold gold; design -copy-from gate -as gate gate
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple -seq 5
equiv_induct -seq 5
equiv_status -assert
"""
    # paths relative to the repo: the WebAssembly build of yosys only sees cwd
    with tempfile.NamedTemporaryFile("w", suffix=".ys", dir=ROOT, delete=False) as f:
        f.write(script)
    t0 = time.time()
    try:
        p = subprocess.run([YOSYS, "-q", "-s", Path(f.name).name], cwd=ROOT,
                           capture_output=True, text=True, timeout=TIMEOUT)
        log = (p.stdout + p.stderr)[-400:]
        if p.returncode == 0:
            status = "proved"
        elif "unproven $equiv" in log:
            status = "timeout"          # method ran out of strength: not proved
        else:
            status = "unknown"          # tool error: excluded from scoring
    except subprocess.TimeoutExpired:
        status, log = "timeout", "wall-clock timeout"
    finally:
        os.unlink(f.name)
    return status, round(time.time() - t0, 1), log


def main(extra):
    if not YOSYS:
        sys.exit("no yosys found (set YOSYS=...)")
    ext = HERE / "_ext"
    ext.mkdir(exist_ok=True)
    for e in extra:
        shutil.copy(e, ext)
    files = [p.relative_to(ROOT).as_posix() for p in
             sorted(probes().glob("*.v")) + sorted((ROOT / "examples").glob("*.v"))
             + [ext / Path(e).name for e in extra]]
    shutil.rmtree(STORE, ignore_errors=True)

    rvs = [sys.executable, "-m", "rvsched"]
    routed = json.loads(subprocess.run(rvs + ["route", *files, "--store", STORE],
                                       cwd=ROOT, capture_output=True, text=True,
                                       check=True).stdout)

    def one(r):
        status, secs, log = prove(files, r["module"])
        return r, status, secs, log

    rows = []
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for r, status, secs, log in ex.map(one, routed):
            rec = subprocess.run(rvs + ["record", *files, "--module", r["module"],
                                        "--engine", "FORMAL", "--status", status,
                                        "--seconds", str(secs), "--store", STORE],
                                 cwd=ROOT, capture_output=True, text=True)
            rows.append({"module": r["module"], "predicted": r["prediction"]["engine"],
                         "actual": status, "seconds": secs,
                         "recorded": rec.returncode == 0,
                         "log": log if status == "unknown" else ""})
            print(f"{r['module']:<24} predicted {r['prediction']['engine']:<13} "
                  f"formal {status:<8} {secs:>6}s", flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
