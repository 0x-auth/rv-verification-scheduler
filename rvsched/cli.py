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


def main(argv=None):
    p = argparse.ArgumentParser(prog="rvsched",
                                description="Decide formal vs simulation before you spend the compute.")
    p.add_argument("--version", action="version", version=f"rvsched {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--store", default=".rvsched",
                        help="directory, or https:// raw URL (read-only). default: .rvsched")
        sp.add_argument("--lang", default="verilog")
        sp.add_argument("-D", "--define", action="append", default=[],
                        help="preprocessor define used by your flow (folded into the fingerprint)")

    r = sub.add_parser("route", help="recommend an engine for every module")
    r.add_argument("files", nargs="+")
    r.add_argument("--metrics", action="store_true", help="include raw metrics")
    common(r)
    r.set_defaults(fn=cmd_route)

    w = sub.add_parser("record", help="write what a tool actually did")
    w.add_argument("files", nargs="+")
    w.add_argument("--module", required=True)
    w.add_argument("--engine", required=True, choices=ENGINES)
    w.add_argument("--status", required=True, choices=STATUSES)
    w.add_argument("--seconds", type=float)
    w.add_argument("--evidence", help="URL or path to the log/proof")
    common(w)
    w.set_defaults(fn=cmd_record)

    c = sub.add_parser("calibrate", help="how often predictions missed reality")
    common(c)
    c.set_defaults(fn=cmd_calibrate)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (KeyError, ValueError, PermissionError, OSError) as e:
        print(f"rvsched: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
