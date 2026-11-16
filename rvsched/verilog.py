"""Verilog / SystemVerilog language plugin.

split       one file -> its modules, interfaces, packages
recognize   the original parse_core + ttc logic, unchanged in spirit
fingerprint rename-invariant structural hash (Merkle over instantiated units)
"""
from __future__ import annotations

import ast
import hashlib
import operator
import re

from .core import Verdict, language

# --- calibratable thresholds (tune against real formal-tool runs) ----------
WIDE_MULT_BITS = 8     # var*var on operands WIDER than this kills unbounded proof
                       # (bench: 8-bit operands proved, 10-bit did not)
STATE_BITS_HARD = 64   # flop state beyond this rarely proves unbounded
STATE_BITS_SOFT = 24   # above this, prefer bounded/hybrid over full proof
UNRESOLVED_WIDTH = 32  # width assumed when [A-1:0] cannot be resolved.
                       # Guessing high is the safe direction (see README).

KEYWORDS = set("""
always always_ff always_comb always_latch and assign assert assume automatic
begin bit buf byte case casex casez cover default defparam disable do else end
endcase endfunction endgenerate endinterface endmodule endpackage endproperty
endtask enum for force forever fork function generate genvar if iff import
initial inout input int integer interface join join_any join_none localparam
logic longint macromodule modport module nand negedge nor not or output package
packed parameter posedge property real reg repeat return shortint signed static
restrict struct supply0 supply1 task time tri typedef union unique unique0 priority
unsigned var void wait while wire xor xnor
""".split())

_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/', re.DOTALL)
_UNIT = re.compile(
    r'\b(module|macromodule|interface|package)\s+(?:automatic\s+|static\s+)?'
    r'([A-Za-z_]\w*)(.*?)\b(endmodule|endinterface|endpackage)\b', re.DOTALL)
_TOKEN = re.compile(
    r"""\(\*[^()*][^()]*?\*\)                    # (* attribute *)
      | (?:\d[\d_]*\s*)?'[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ_?]+   # based literal
      | \d[\d_]*(?:\.\d+)?                     # number
      | \$[A-Za-z_]\w*                         # system task
      | `[A-Za-z_]\w*                          # macro
      | [A-Za-z_]\w*                           # identifier
      | "(?:\\.|[^"\\])*"                      # string
      | <<<|>>>|===|!==|<<=|>>=|\|->|\|=>|::|<=|>=|==|!=|&&|\|\||<<|>>|\*\*|\+:|-:|\#\#
      | \S""", re.VERBOSE)
_SAFE_MACROS = {"`timescale", "`default_nettype", "`resetall",
                "`celldefine", "`endcelldefine", "`define", "`undef",
                "`ifdef", "`ifndef", "`elsif", "`else", "`endif"}
_NAMES_MACRO = {"`define", "`undef", "`ifdef", "`ifndef", "`elsif"}
_DEFINE = re.compile(r'`define\s+([A-Za-z_]\w*)((?:\\\n|[^\n])*)')


def strip_comments(text: str) -> str:
    return _COMMENTS.sub(' ', text)


# ------------------------------------------------------------------ widths --
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv, ast.Div: operator.floordiv,
        ast.Pow: operator.pow}


def _eval(expr: str):
    """Integer arithmetic only. Anything else -> None."""
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ValueError
    try:
        return ev(ast.parse(expr, mode='eval').body)
    except Exception:
        return None


def _params(src: str) -> dict:
    """parameter / localparam NAME = <int expr>, resolved in order."""
    out = {}
    for m in re.finditer(r'\b(?:parameter|localparam)\b([^;)]*)', src):
        for part in m.group(1).split(','):
            pm = re.match(r'\s*(?:\w+\s+)*?(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*=\s*(.+)', part)
            if pm:
                v = _eval(_subst(pm.group(2).strip(), out))
                if v is not None:
                    out[pm.group(1)] = v
    return out


def _subst(expr: str, params: dict) -> str:
    expr = re.sub(r"\d*'[sS]?[dD](\d+)", r'\1', expr)
    return re.sub(r'\b[A-Za-z_]\w*\b',
                  lambda m: str(params.get(m.group(0), m.group(0))), expr)


def _width(rng: str, params: dict):
    """'[msb:lsb]' -> (bits, resolved?)"""
    if not rng:
        return 1, True
    m = re.match(r'\[\s*(.+?)\s*:\s*(.+?)\s*\]', rng)
    if not m:
        return 1, True
    hi, lo = _eval(_subst(m.group(1), params)), _eval(_subst(m.group(2), params))
    if hi is None or lo is None:
        return UNRESOLVED_WIDTH, False
    return abs(hi - lo) + 1, True


# ----------------------------------------------------------------- metrics --
def metrics(src: str) -> dict:
    """Static estimate from source. Not elaboration. Deliberately cheap."""
    src = strip_comments(src)
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)   # "%d" in $display is not modulo
    src = re.sub(r'^\s*`timescale[^\n]*', '', src, flags=re.M)  # "1 ns / 1 ps"
    params = _params(src)
    m = {"module_name": "unknown", "control_ops": 0, "cheap_arith_ops": 0,
         "nonlinear_arith_ops": 0, "nonlinear_detail": [],
         "nonlinear_operand_width": 0,
         "sequential_state_bits": 0, "max_datapath_width": 0,
         "unresolved_widths": 0, "sv_interfaces": 0, "sv_structs": 0,
         "sva_assertions": 0, "rvvi_hooks": 0}

    mm = re.search(r'\b(?:module|macromodule)\s+(\w+)', src)
    if mm:
        m["module_name"] = mm.group(1)

    # 1. width-weighted state. `reg [7:0] a, b, c;` is 24 bits; inputs are
    #    not state; `output reg` is. Undercounting is the unsafe direction.
    not_names = {'input', 'output', 'inout', 'var', 'signed', 'unsigned',
                 'reg', 'logic', 'wire', 'bit', 'automatic', 'static'}
    decl = re.compile(r'\b(input|output|inout)?\s*(?:var\s+)?\b(?:reg|logic)\b'
                      r'\s*(?:signed|unsigned)?\s*(\[[^\]]*\])?([^;)\n]*)')
    for d in decl.finditer(src):
        direction, rng, tail = d.group(1), d.group(2), d.group(3) or ''
        if direction == 'input':
            continue
        w, ok = _width(rng or '', params)
        if not ok:
            m["unresolved_widths"] += 1
        head = tail.split('=')[0]
        total = 0
        # each name may carry unpacked dims: `reg [31:0] regs [0:30]` = 31 x 32
        for nm, dims in re.findall(r'\b([A-Za-z_]\w*)\s*((?:\[[^\]]*\]\s*)*)', head):
            if nm in not_names:
                continue
            depth = 1
            for dim in re.findall(r'\[[^\]]*\]', dims):
                dw, ok2 = _width(dim, params)
                if not ok2:
                    m["unresolved_widths"] += 1
                depth *= dw
            total += w * depth
        m["sequential_state_bits"] += total or w
        m["max_datapath_width"] = max(m["max_datapath_width"], w)

    # widths of every declared signal, inputs included, for operand sizing
    widths = {}
    for d in re.finditer(r'(?=\b(?:input|output|inout|wire|reg|logic)\b\s*(?:wire|reg|logic)?'
                         r'\s*(?:signed|unsigned)?\s*(\[[^\]]*\])?([^;)\n]*))', src):
        w, _ = _width(d.group(1) or '', params)
        for seg in d.group(2).split(','):
            if re.search(r'\b(?:input|output|inout|wire|reg|logic)\b', seg):
                break                      # next declaration starts here
            nm = re.match(r'\s*([A-Za-z_]\w*)', seg)
            if nm:
                widths.setdefault(nm.group(1), w)

    def operand_width(t):
        base = re.match(r'[A-Za-z_]\w*', t).group(0)
        sl = re.search(r'\[[^\]]*:[^\]]*\]', t)
        if sl:
            w, ok = _width(sl.group(0), params)
            return w if ok else UNRESOLVED_WIDTH
        if re.search(r'\[', t):
            return 1
        return widths.get(base, UNRESOLVED_WIDTH)

    # 2. nonlinear arithmetic: var*var, /, %. Constant operand is cheap.
    ident = r'[A-Za-z_]\w*(?:\s*\[[^\]]*\])?'
    for op in ('*', '/', '%'):
        pat = re.compile(r'(' + ident + r')\s*' + re.escape(op) +
                         r'(?!\*)\s*(' + ident + r"|\d+(?:'[bBoOdDhH]\w+)?)")
        for t in pat.finditer(src):
            lhs, rhs = t.group(1).strip(), t.group(2).strip()
            if re.match(r'^\d', rhs) or rhs in params:
                m["cheap_arith_ops"] += 1
            else:
                m["nonlinear_arith_ops"] += 1
                m["nonlinear_detail"].append(f"{lhs} {op} {rhs}")
                m["nonlinear_operand_width"] = max(m["nonlinear_operand_width"],
                                                   operand_width(lhs), operand_width(rhs))
    for op in ('+', '-', '<<', '>>', '&', '|', '^'):
        m["cheap_arith_ops"] += src.count(op)

    # 3. control and metadata
    for kw in ('always', 'always_ff', 'always_comb', 'if', 'else',
               'case', 'casex', 'casez'):
        m["control_ops"] += len(re.findall(r'\b' + kw + r'\b', src))
    m["sv_interfaces"] = len(re.findall(r'\binterface\b', src)) // 2
    m["sv_structs"] = len(re.findall(r'\bstruct\b', src))
    m["sva_assertions"] = len(re.findall(r'\b(assert|assume|cover)\s+property\b', src))
    for pat in (r'\brvvi_\w+\b', r'\bRVVI\b', r'\brvfi_\w+\b', r'\bRVFI\b'):
        m["rvvi_hooks"] += len(re.findall(pat, src))
    return m


def classify(m: dict):
    """Most decisive signal first. Returns (engine, confidence, reason)."""
    nonlin = m.get("nonlinear_arith_ops", 0)
    bits = m.get("sequential_state_bits", 0)
    dpw = m.get("max_datapath_width", 0)
    opw = m.get("nonlinear_operand_width", dpw)   # older metrics lack it
    control = m.get("control_ops", 0)
    rvvi, sva = m.get("rvvi_hooks", 0), m.get("sva_assertions", 0)

    if nonlin > 0 and opw > WIDE_MULT_BITS:
        return ("SIMULATION", 0.97,
                f"{nonlin} nonlinear op(s) (var*var / div / mod) with operands up "
                f"to {opw} bits. Unbounded formal will not converge; simulate or BMC.")
    if nonlin > 0:
        return ("HYBRID_SPLIT", 0.80,
                f"{nonlin} narrow nonlinear op(s) ({opw}-bit operands). Bounded formal is viable.")
    if bits > STATE_BITS_HARD:
        return ("SIMULATION", 0.90,
                f"{bits} bits of state exceed the unbounded proof budget ({STATE_BITS_HARD}).")
    if rvvi > 0 or sva > 0:
        return ("FORMAL", 0.95,
                f"Compliance/assertion hooks present (rvvi/rvfi={rvvi}, sva={sva}).")
    if bits <= STATE_BITS_SOFT and control > 0:
        return ("FORMAL", 0.92,
                f"Control-dominated, {bits} state bits, no nonlinear arithmetic.")
    return ("HYBRID_SPLIT", 0.70,
            f"{bits} state bits, no nonlinear arithmetic. Formal the control, "
            f"simulate the wide datapath.")


# -------------------------------------------------------------- fingerprint --
def _declared(src: str, toks: list[str]) -> set:
    """Names this unit introduces. Only these are renamed."""
    names = set()

    def idents(s):
        return [t for t in re.findall(r'[A-Za-z_]\w*', s) if t not in KEYWORDS]

    # unit name
    m = _UNIT.match(src.lstrip())
    if m:
        names.add(m.group(2))
    # declaration statements: keep each comma segment's name, drop ranges/defaults
    # Lookahead so every keyword starts its own match (ports share one ';').
    for d in re.finditer(r'(?=\b(?:input|output|inout|reg|wire|logic|integer|genvar|'
                         r'parameter|localparam|bit|byte|int|shortint|longint|'
                         r'real|time|tri|supply0|supply1|var)\b([^;]*))', src):
        body = re.sub(r'\[[^\]]*\]', ' ', d.group(1))
        depth, seg, segs = 0, '', []
        for ch in body:
            if ch in '({':
                depth += 1
            elif ch in ')}':
                depth -= 1
                if depth < 0:
                    break                     # end of this declaration list
            if ch == ',' and depth == 0:
                segs.append(seg)
                seg = ''
            else:
                seg += ch
        segs.append(seg)
        for s in segs:
            ids = idents(s.split('=', 1)[0])
            if ids:
                names.add(ids[-1])
    # typedef ... NAME;   enum { A, B = 2 }   function/task names   labels
    for t in re.finditer(r'\btypedef\b(?:[^;{]|\{(?:[^{}]|\{[^{}]*\})*\})*?([A-Za-z_]\w*)\s*;', src):
        names.add(t.group(1))
    for e in re.finditer(r'\benum\b[^{]*\{([^}]*)\}', src):
        for part in e.group(1).split(','):
            ids = idents(part.split('=')[0])
            if ids:
                names.add(ids[0])
    for f in re.finditer(r'\b(?:function|task)\b(?:\s+automatic)?[^;(]*?([A-Za-z_]\w*)\s*[(;]', src):
        names.add(f.group(1))
    for lb in re.finditer(r'\b(?:begin|fork|end|join)\s*:\s*([A-Za-z_]\w*)', src):
        names.add(lb.group(1))
    # TYPE NAME (declaration or instance): second identifier is introduced
    for i in range(len(toks) - 1):
        a, b = toks[i], toks[i + 1]
        if _is_id(a) and _is_id(b) and a not in KEYWORDS and b not in KEYWORDS \
                and (i == 0 or toks[i - 1] != '.'):
            names.add(b)
    # instance after parameter override:  TYPE #( ... ) NAME (
    for inst in re.finditer(r'\b[A-Za-z_]\w*\s*#\s*\((?:[^()]|\([^()]*\))*\)\s*([A-Za-z_]\w*)', src):
        names.add(inst.group(1))
    return names


def _is_id(t: str) -> bool:
    return bool(re.match(r'[A-Za-z_]\w*$', t))


class Verilog:
    name = "verilog"

    def split(self, text: str):
        """Units are modules, interfaces, packages, and `define macros
        (named '`NAME'), so a macro used in a module is part of its hash."""
        text = strip_comments(text)
        out = [('`' + m.group(1), m.group(0).strip()) for m in _DEFINE.finditer(text)]
        out += [(m.group(2), m.group(0)) for m in _UNIT.finditer(text)]
        return out

    def children(self, src: str, units: dict) -> set:
        """Modules instantiated (transitively) by this one, among `units`."""
        seen, todo = set(), [src]
        while todo:
            toks = _TOKEN.findall(todo.pop())
            for i, t in enumerate(toks):
                if t in units and t not in seen and (i == 0 or toks[i - 1] != '.') \
                        and units[t].lstrip().startswith(('module', 'macromodule')):
                    seen.add(t)
                    todo.append(units[t])
        return seen

    def recognize(self, src: str, units: dict | None = None) -> Verdict:
        """With `units`, state and nonlinear ops of instantiated submodules
        are added in, so a wrapper around a CPU is judged as a CPU."""
        m = metrics(src)
        kids = self.children(src, units or {}) - {m["module_name"]}
        for k in sorted(kids):
            c = metrics(units[k])
            for key in ("sequential_state_bits", "nonlinear_arith_ops",
                        "unresolved_widths", "rvvi_hooks", "sva_assertions"):
                m[key] += c[key]
            m["nonlinear_detail"] += [f"{k}: {d}" for d in c["nonlinear_detail"]]
            m["max_datapath_width"] = max(m["max_datapath_width"], c["max_datapath_width"])
        m["submodules"] = sorted(kids)
        engine, conf, why = classify(m)
        if kids:
            why += f" (includes {len(kids)} submodule(s).)"
        if m["unresolved_widths"]:
            why += (f" ({m['unresolved_widths']} width(s) could not be resolved;"
                    f" assumed {UNRESOLVED_WIDTH} bits each.)")
            conf = round(conf * 0.9, 2)
        return Verdict(engine=engine, confidence=conf, reason=why,
                       recognizer="verilog/static-v1", metrics=m)

    def fingerprint(self, units: dict) -> dict:
        """units: {name: source}. Returns {name: 'sha256:...' or None}.

        Renames every name a unit declares, in order of first use, so two units
        that differ only by naming hash the same. Names of other units in the
        input are replaced by THEIR fingerprint (Merkle), so a parent changes
        when a child changes. Anything referenced but not visible here (an
        unknown module, a package, an undefined macro, an include) makes the
        fingerprint None: unstable, never cached. That is the safe direction.
        """
        out, busy = {}, set()

        def fp(name):
            if name in out:
                return out[name]
            if name in busy:          # recursion through generate etc.: give up
                return None
            busy.add(name)
            src = units[name]
            if name.startswith('`'):            # a macro: hash its text as-is
                busy.discard(name)
                body = ' '.join(_TOKEN.findall(src))
                out[name] = 'sha256:' + hashlib.sha256(body.encode()).hexdigest()
                return out[name]
            toks = _TOKEN.findall(src)
            declared = _declared(src, toks)
            rename, norm, stable = {}, [], True
            for i, t in enumerate(toks):
                if t.startswith('`') and t in units and t != name:   # known macro
                    child = fp(t)
                    norm.append('@' + (child or t))
                    stable &= child is not None
                elif t.startswith('`'):
                    if t not in _SAFE_MACROS:
                        stable = False
                    norm.append(t)
                elif i and toks[i - 1] in _NAMES_MACRO:   # `ifdef NAME: literal
                    norm.append(t)
                elif not _is_id(t) or t in KEYWORDS:
                    norm.append(re.sub(r'\s+', '', t) if "'" in t and t[0] != '"' else t)
                elif i and toks[i - 1] == '.':          # member / port name
                    norm.append(t)
                elif t in units and t != name:          # another unit: Merkle
                    child = fp(t)
                    if child is None:
                        stable = False
                    norm.append('@' + (child or t))
                elif t in declared:
                    rename.setdefault(t, f"v{len(rename)}")
                    norm.append(rename[t])
                else:
                    stable = False                      # external, unseen
                    norm.append(t)
            busy.discard(name)
            out[name] = ('sha256:' + hashlib.sha256(' '.join(norm).encode()).hexdigest()
                         if stable else None)
            return out[name]

        for n in units:
            fp(n)
        return out


language("verilog")(Verilog)
