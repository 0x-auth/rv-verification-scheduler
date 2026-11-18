"""rvsched route | record | calibrate"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .core import ENGINES, STATUSES, Outcome, decide, get_language, open_store
from .core import record as record_verb
from .core import resolve


def _units(files, lang):
    """All units across all files, so children in other files are visible."""
    units, origin = {}, {}
    for f in files:
        for name, src in lang.split(Path(f).read_text(errors="replace")):
            units[name], origin[name] = src, f
    return units, origin


def _fingerprints(lang, units, defines):
    """-D flags change the design without changing the text, so they are
    folded into every fingerprint."""
    fps = lang.fingerprint(units)
    if not defines:
        return fps
    salt = "|".join(sorted(defines))
    return {k: (None if v is None else
                "sha256:" + hashlib.sha256(f"{v}|{salt}".encode()).hexdigest())
            for k, v in fps.items()}


def cmd_route(a):
    lang, st = get_language(a.lang), open_store(a.store)
    units, origin = _units(a.files, lang)
    fps = _fingerprints(lang, units, a.define)
    rows = []
    for name, src in units.items():
        if not src.lstrip().startswith(("module", "macromodule")):
            continue                       # interfaces/packages: deps only
        pred = lang.recognize(src, units)
        fp = fps.get(name)
        known = resolve(fp, st) if fp else None
        rows.append({"module": name, "file": origin[name], "fingerprint": fp,
                     "decision": decide(pred, known),
                     "prediction": {"engine": pred.engine,
                                    "confidence": pred.confidence},
                     "metrics": pred.metrics if a.metrics else None})
    if not a.metrics:
        for r in rows:
            r.pop("metrics")
    print(json.dumps(rows, indent=2))
    return 0


def cmd_record(a):
    lang, st = get_language(a.lang), open_store(a.store)
    units, _ = _units(a.files, lang)
    if a.module not in units:
        print(f"module {a.module!r} not found in {a.files}", file=sys.stderr)
        return 2
    fp = _fingerprints(lang, units, a.define)[a.module]
    if fp is None:
        print(f"{a.module}: fingerprint is unstable (depends on something not in "
              f"the given files); pass those files too", file=sys.stderr)
        return 3
    pred = lang.recognize(units[a.module], units)
    r = record_verb(fp, a.module, pred,
                    Outcome(engine=a.engine, status=a.status,
                            seconds=a.seconds, evidence=a.evidence), st)
    print(json.dumps(r.to_dict(), indent=2))
    return 0


def cmd_calibrate(a):
    st = open_store(a.store)
    pairs, misses, total = Counter(), [], 0
    for r in st.all():
        if r.miss is None:
            continue
        total += 1
        pairs[f"{r.prediction.engine} -> {r.outcome.engine}:{r.outcome.status}"] += 1
        if r.miss:
            misses.append({"module": r.module, "predicted": r.prediction.engine,
                           "actual": f"{r.outcome.engine}:{r.outcome.status}",
                           "metrics": {k: r.prediction.metrics.get(k) for k in
                                       ("sequential_state_bits", "nonlinear_arith_ops",
                                        "max_datapath_width")}})
    print(json.dumps({"records_with_outcome": total,
                      "misses": len(misses),
                      "miss_rate": round(len(misses) / total, 3) if total else None,
                      "pairs": dict(pairs), "miss_detail": misses}, indent=2))
    return 0


HELP = """\
Decide formal vs simulation for each RTL module before you spend the compute,
and never prove the same structure twice. No solver runs, no AI model.

start with `rvsched route -h`.

examples:
  rvsched route rtl/*.v
  rvsched route rtl/*.v --metrics                 # include the numbers behind each verdict
  rvsched record rtl/*.v --module fifo --engine FORMAL --status proved \\
      --seconds 42 --evidence https://ci.example/run/42
  rvsched calibrate
  rvsched route rtl/*.v --store https://raw.githubusercontent.com/you/repo/main/.rvsched

output: JSON on stdout. exit codes: 0 ok, 2 bad input, 3 module cannot be fingerprinted.
docs: https://github.com/0x-auth/rv-verification-scheduler/blob/main/USAGE.md
"""

ROUTE_HELP = """\
For each module in the given files, print a decision:

  SKIP        this exact structure was already proved (evidence attached)
  KNOWN_FAIL  this exact structure already failed formal; fix the design first
  RUN         run it on the given engine: FORMAL, SIMULATION or HYBRID_SPLIT

Pass every file the design needs. Submodules, interfaces, packages and `define
macros found in other files are part of a module's fingerprint; anything not
given makes the fingerprint null (never cached, only recognized).

examples:
  rvsched route rtl/*.v rtl/*.sv
  rvsched route top.v -D FORMAL -D SYNTH
  rvsched route rtl/*.v --metrics | jq '.[] | {module, engine: .decision.engine}'
"""

RECORD_HELP = """\
Record a real tool outcome for one module. Recorded outcomes override
predictions on every later `route`, in this repo or anywhere the same
structure appears (renamed or not).

statuses:
  proved   formal proved it            -> later routes SKIP it
  failed   formal found a bug          -> later routes say KNOWN_FAIL
  timeout  formal did not finish       -> later routes send it to SIMULATION
  unknown  the run told you nothing    -> ignored

examples:
  rvsched record rtl/*.v --module alu --engine FORMAL --status timeout --seconds 3600
  rvsched record rtl/*.v --module fifo --engine FORMAL --status proved \\
      --evidence https://github.com/you/repo/actions/runs/123
"""

CAL_HELP = """\
Read every recorded outcome and report where predictions were wrong
(e.g. predicted FORMAL but formal timed out). Use it to tune the thresholds
at the top of rvsched/verilog.py for your tool.

example:
  rvsched calibrate --store .rvsched
"""


def main(argv=None):
    fmt = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(prog="rvsched", description=HELP, formatter_class=fmt)
    p.add_argument("-V", "--version", action="version", version=f"rvsched {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    def common(sp):
        sp.add_argument("--store", default=".rvsched", metavar="DIR|URL",
                        help="where records live: a directory (default .rvsched) or the "
                             "https raw URL of a committed store (read-only)")
        sp.add_argument("--lang", default="verilog",
                        help="language plugin (default verilog; plugins can add more)")
        sp.add_argument("-D", "--define", action="append", default=[], metavar="NAME",
                        help="preprocessor define your flow uses; folded into the "
                             "fingerprint (repeatable)")

    r = sub.add_parser("route", help="recommend an engine for every module",
                       description=ROUTE_HELP, formatter_class=fmt)
    r.add_argument("files", nargs="+", help="Verilog/SystemVerilog files")
    r.add_argument("--metrics", action="store_true",
                   help="include the raw metrics behind each verdict")
    common(r)
    r.set_defaults(fn=cmd_route)

    w = sub.add_parser("record", help="write what a tool actually did",
                       description=RECORD_HELP, formatter_class=fmt)
    w.add_argument("files", nargs="+", help="the same files you routed")
    w.add_argument("--module", required=True, help="module name")
    w.add_argument("--engine", required=True, choices=ENGINES, help="engine that ran")
    w.add_argument("--status", required=True, choices=STATUSES, help="what happened")
    w.add_argument("--seconds", type=float, help="run time")
    w.add_argument("--evidence", metavar="URL|PATH", help="link to the log or proof")
    common(w)
    w.set_defaults(fn=cmd_record)

    c = sub.add_parser("calibrate", help="how often predictions missed reality",
                       description=CAL_HELP, formatter_class=fmt)
    common(c)
    c.set_defaults(fn=cmd_calibrate)

    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 0
    try:
        return a.fn(a)
    except (KeyError, ValueError, PermissionError, OSError) as e:
        print(f"rvsched: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
