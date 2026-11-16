#!/usr/bin/env python3
"""Kept for compatibility. The logic now lives in rvsched/verilog.py.

    python3 parse_core.py file.v | python3 ttc
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rvsched.verilog import metrics  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_core.py <verilog_file>")
        sys.exit(1)
    try:
        src = Path(sys.argv[1]).read_text()
    except FileNotFoundError:
        print(f"Error: File {sys.argv[1]} not found.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(metrics(src), indent=4))
