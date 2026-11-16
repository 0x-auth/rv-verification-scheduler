import json
import subprocess
import sys
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from rvsched import Outcome, decide, get_language, open_store, record, resolve
from rvsched.cli import main

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
V = get_language("verilog")

FIFO = """
module fifo #(parameter W = 8) (input wire clk, input wire [W-1:0] d, output reg [W-1:0] q);
  reg [W-1:0] mem;
  always @(posedge clk) begin mem <= d; q <= mem; end
endmodule
"""
FIFO_RENAMED = FIFO.replace("fifo", "buffer").replace("mem", "store").replace(" q", " out").replace("q <=", "out <=")
TOP = """
module top (input wire clk, input wire [7:0] a, output wire [7:0] y);
  fifo #(.W(8)) u0 (.clk(clk), .d(a), .q(y));
endmodule
"""


def units(*srcs):
    out = {}
    for s in srcs:
        out.update(dict(V.split(s)))
    return out


# ---- fingerprint ----------------------------------------------------------
def test_rename_invariant():
    a = V.fingerprint(units(FIFO))["fifo"]
    b = V.fingerprint(units(FIFO_RENAMED))["buffer"]
    assert a and a == b


def test_comments_and_whitespace_ignored():
    noisy = FIFO.replace("always", "// note\n   always   /* x */")
    assert V.fingerprint(units(FIFO))["fifo"] == V.fingerprint(units(noisy))["fifo"]


def test_real_change_changes_hash():
    changed = FIFO.replace("q <= mem", "q <= ~mem")
    assert V.fingerprint(units(FIFO))["fifo"] != V.fingerprint(units(changed))["fifo"]


def test_child_change_propagates_to_parent():
    t1 = V.fingerprint(units(FIFO, TOP))["top"]
    t2 = V.fingerprint(units(FIFO.replace("q <= mem", "q <= ~mem"), TOP))["top"]
    assert t1 and t2 and t1 != t2


def test_unknown_child_is_unstable():
    assert V.fingerprint(units(TOP))["top"] is None


def test_external_macro_is_unstable():
    m = "module m(input wire [`W-1:0] a, output reg b); always @(*) b = a[0]; endmodule"
    assert V.fingerprint(units(m))["m"] is None


def test_safe_macro_is_stable():
    m = "`timescale 1ns/1ps\nmodule m(input wire a, output reg b); always @(*) b = a; endmodule"
    assert V.fingerprint(units(m))["m"] is not None


def test_interface_and_typedef_resolve():
    src = (EX / "sample_advanced.sv").read_text()
    assert V.fingerprint(units(src))["riscv_decoder_advanced"] is not None


# ---- recognizer -----------------------------------------------------------
def test_multi_decl_regression():
    src = (EX / "sample_multi_decl.v").read_text()
    assert V.recognize(src).metrics["sequential_state_bits"] == 72


def test_parameter_widths_resolved():
    v = V.recognize(FIFO)
    assert v.metrics["unresolved_widths"] == 0
    assert v.metrics["sequential_state_bits"] == 16


def test_unresolved_width_guesses_high():
    m = "module m(input wire clk, output reg [N-1:0] q); always @(posedge clk) q <= 0; endmodule"
    v = V.recognize(m)
    assert v.metrics["unresolved_widths"] == 1
    assert v.metrics["sequential_state_bits"] == 32


def test_multiplier_goes_to_simulation():
    v = V.recognize((EX / "sample_arithmetic.v").read_text())
    assert v.engine == "SIMULATION"


def test_const_multiply_is_cheap():
    m = "module m(input wire clk, input wire [15:0] a, output reg [15:0] q); always @(posedge clk) q <= a * 4; endmodule"
    assert V.recognize(m).metrics["nonlinear_arith_ops"] == 0


def test_parameter_multiply_is_cheap():
    m = "module m #(parameter K=3)(input wire clk, input wire [15:0] a, output reg [15:0] q); always @(posedge clk) q <= a * K; endmodule"
    assert V.recognize(m).metrics["nonlinear_arith_ops"] == 0


# ---- store + decide -------------------------------------------------------
def _fp():
    return V.fingerprint(units(FIFO))["fifo"]


def test_void_then_record_then_resolve(tmp_path):
    st = open_store(str(tmp_path))
    fp = _fp()
    assert resolve(fp, st) is None
    pred = V.recognize(FIFO)
    record(fp, "fifo", pred, Outcome("FORMAL", "proved", 3.2, "ci://run/1"), st)
    got = resolve(fp, st)
    assert got.outcome.status == "proved" and got.outcome.evidence == "ci://run/1"


def test_rename_hits_same_record(tmp_path):
    st = open_store(str(tmp_path))
    record(_fp(), "fifo", V.recognize(FIFO), Outcome("FORMAL", "proved"), st)
    fp2 = V.fingerprint(units(FIFO_RENAMED))["buffer"]
    assert decide(V.recognize(FIFO_RENAMED), resolve(fp2, st))["action"] == "SKIP"


def test_truth_beats_prediction():
    pred = V.recognize(FIFO)                        # predicts FORMAL
    assert pred.engine == "FORMAL"
    from rvsched import Record
    known = Record(_fp(), "fifo", pred, Outcome("FORMAL", "timeout"))
    d = decide(pred, known)
    assert d["engine"] == "SIMULATION" and known.miss is True


def test_bad_outcome_rejected(tmp_path):
    with pytest.raises(ValueError):
        record(_fp(), "fifo", V.recognize(FIFO), Outcome("FORMAL", "maybe"), open_store(str(tmp_path)))


def test_http_store_reads_committed_dir(tmp_path):
    st = open_store(str(tmp_path))
    record(_fp(), "fifo", V.recognize(FIFO), Outcome("FORMAL", "proved"), st)
    srv = HTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        remote = open_store(f"http://127.0.0.1:{srv.server_port}")
    except KeyError:
        # only https is registered; register http for the test the same way a plugin would
        from rvsched.core import store
        from rvsched.stores import HttpStore
        store("http")(HttpStore)
        remote = open_store(f"http://127.0.0.1:{srv.server_port}")
    try:
        assert remote.get(_fp()).outcome.status == "proved"
        assert remote.get("sha256:" + "0" * 64) is None
        with pytest.raises(PermissionError):
            remote.put(resolve(_fp(), st))
    finally:
        srv.shutdown()


# ---- cli ------------------------------------------------------------------
def test_cli_route_record_calibrate(tmp_path, capsys):
    f = tmp_path / "fifo.v"
    f.write_text(FIFO)
    store = str(tmp_path / "s")
    assert main(["route", str(f), "--store", store]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["decision"]["action"] == "RUN"
    assert main(["record", str(f), "--module", "fifo", "--engine", "FORMAL",
                 "--status", "timeout", "--store", store]) == 0
    capsys.readouterr()
    assert main(["route", str(f), "--store", store]) == 0
    assert json.loads(capsys.readouterr().out)[0]["decision"]["engine"] == "SIMULATION"
    assert main(["calibrate", "--store", store]) == 0
    cal = json.loads(capsys.readouterr().out)
    assert cal["misses"] == 1 and cal["records_with_outcome"] == 1


def test_cli_record_unstable_refused(tmp_path):
    f = tmp_path / "top.v"
    f.write_text(TOP)
    assert main(["record", str(f), "--module", "top", "--engine", "FORMAL",
                 "--status", "proved", "--store", str(tmp_path / "s")]) == 3


def test_legacy_pipeline_still_works():
    p = subprocess.run([sys.executable, "parse_core.py", "examples/sample_arithmetic.v"],
                       cwd=ROOT, capture_output=True, text=True, check=True)
    t = subprocess.run([sys.executable, "ttc"], input=p.stdout, cwd=ROOT,
                       capture_output=True, text=True, check=True)
    assert json.loads(t.stdout)["recommended_engine"] == "SIMULATION"


def test_macro_defined_in_input_is_stable_and_tracked():
    m = "`define W 8\nmodule m(input wire [`W-1:0] a, output reg b); always @(*) b = a[0]; endmodule"
    fp1 = V.fingerprint(units(m))["m"]
    fp2 = V.fingerprint(units(m.replace("`define W 8", "`define W 16")))["m"]
    assert fp1 and fp2 and fp1 != fp2


def test_ifdef_name_is_not_external():
    m = "module m(input wire a, output reg b);\n`ifdef FORMAL\n always @(*) assert(b == a);\n`endif\n always @(*) b = a; endmodule"
    assert V.fingerprint(units(m))["m"] is not None


def test_defines_change_fingerprint(tmp_path, capsys):
    f = tmp_path / "fifo.v"
    f.write_text(FIFO)
    main(["route", str(f), "--store", str(tmp_path / "s")])
    a = json.loads(capsys.readouterr().out)[0]["fingerprint"]
    main(["route", str(f), "--store", str(tmp_path / "s"), "-D", "FORMAL"])
    b = json.loads(capsys.readouterr().out)[0]["fingerprint"]
    assert a != b


def test_format_string_is_not_modulo():
    m = 'module m(input wire clk, input wire [7:0] a); always @(posedge clk) $display("%x %d", a, a); endmodule'
    assert V.recognize(m).metrics["nonlinear_arith_ops"] == 0


def test_wrapper_inherits_child_state():
    us = units(FIFO, TOP)
    v = V.recognize(us["top"], us)
    assert v.metrics["submodules"] == ["fifo"]
    assert v.metrics["sequential_state_bits"] == 16


def test_memory_array_counts_every_word():
    m = "module m(input wire clk, input wire [4:0] a, input wire [31:0] d); reg [31:0] regs [0:30]; always @(posedge clk) regs[a] <= d; endmodule"
    assert V.recognize(m).metrics["sequential_state_bits"] == 31 * 32


def test_operand_width_not_output_width_decides():
    narrow = "module m(input wire clk, input wire [7:0] a, input wire [7:0] b, output reg [15:0] p); always @(posedge clk) p <= a * b; endmodule"
    wide = narrow.replace("[7:0]", "[15:0]").replace("[15:0] p", "[31:0] p")
    assert V.recognize(narrow).engine == "HYBRID_SPLIT"
    assert V.recognize(wide).engine == "SIMULATION"
