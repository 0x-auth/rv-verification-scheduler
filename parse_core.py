#!/usr/bin/env python3
"""
parse_core.py - RTL static complexity extractor for verification routing.

Unlike naive keyword counting, this estimates the two structural quantities
that actually predict formal-tool tractability:

  1. sequential_state_bits - the width-weighted count of flip-flop state.
     Formal reachability / BDD size scales with STATE BITS, not register
     *count*. A single `reg [63:0]` is 64 bits of state, not "1", and
     `reg [7:0] a, b, c;` is 24 bits, not 8. Input-direction signals are
     not state; `output reg` is.

  2. nonlinear_arith - variable x variable multiply, divide, and modulo.
     These are the classic model-checker killers. A shift, or a multiply by
     a constant / power of two, is cheap and does NOT count here.

Everything else (control, RVVI hooks, assertions) is secondary metadata.
"""
import re
import sys
import json


class VerilogMetricsParser:
    CONTROL_KEYWORDS = ['always', 'always_ff', 'always_comb', 'if', 'else',
                        'case', 'casex', 'casez']
    # operators that are cheap for formal (linear / bit-parallel)
    CHEAP_OPS = ['+', '-', '<<', '>>', '&', '|', '^']
    # operators that are expensive when both operands are variables
    NONLINEAR_OPS = ['*', '/', '%']

    def _strip_comments(self, s):
        s = re.sub(r'//[^\n]*', '', s)
        s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
        return s

    def _width(self, decl):
        """Return bit width from a '[msb:lsb]' declaration fragment, else 1."""
        m = re.search(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', decl)
        if m:
            hi, lo = int(m.group(1)), int(m.group(2))
            return abs(hi - lo) + 1
        return 1

    def parse_module(self, file_path):
        try:
            with open(file_path, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Error: File {file_path} not found.", file=sys.stderr)
            sys.exit(1)

        content = self._strip_comments(content)

        metrics = {
            "module_name": "unknown",
            "control_ops": 0,
            "cheap_arith_ops": 0,
            "nonlinear_arith_ops": 0,      # var*var, /, %  -> formal killers
            "nonlinear_detail": [],
            "sequential_state_bits": 0,     # width-weighted flop state
            "max_datapath_width": 0,
            "sv_interfaces": 0,
            "sv_structs": 0,
            "sva_assertions": 0,
            "rvvi_hooks": 0,
        }

        m = re.search(r'\bmodule\s+(\w+)', content)
        if m:
            metrics["module_name"] = m.group(1)

        # ---- 1. Sequential state bits ------------------------------------
        # Signals declared reg/logic (optionally with a width) are candidate
        # state. We width-weight every such declaration. This is an estimate,
        # not elaboration, but it tracks BDD/reachability cost far better than
        # counting the keyword.
        #
        # A declaration may name SEVERAL signals: `reg [7:0] a, b, c;` is
        # 24 bits, not 8. An earlier version captured only the first
        # identifier and so UNDER-counted state, which is the unsafe
        # direction for this tool: under-counting routes an intractable
        # module to FORMAL and burns the CI time this pass exists to save.
        #
        # `input`-direction signals are not state and are excluded.
        # `output reg` IS state and is kept.
        NOT_NAMES = {'input', 'output', 'inout', 'var', 'signed', 'unsigned',
                     'reg', 'logic', 'wire', 'bit', 'automatic', 'static'}
        decl_re = re.compile(
            r'\b(input|output|inout)?\s*(?:var\s+)?'
            r'\b(?:reg|logic)\b'
            r'\s*(?:signed|unsigned)?'
            r'\s*(\[[^\]]*\])?'
            r'([^;)\n]*)')
        for decl in decl_re.finditer(content):
            direction, width_txt, tail = decl.group(1), decl.group(2), decl.group(3)
            if direction == 'input':
                continue
            w = self._width(width_txt or '')
            names = [n for n in re.findall(r'\b[A-Za-z_]\w*\b', tail or '')
                     if n not in NOT_NAMES]
            # an assignment or expression tail (`= foo`, `<= bar`) is not a
            # second declared name; stop at the first '=' if present
            if tail and '=' in tail:
                head = tail.split('=')[0]
                names = [n for n in re.findall(r'\b[A-Za-z_]\w*\b', head)
                         if n not in NOT_NAMES]
            n_names = max(len(names), 1)
            metrics["sequential_state_bits"] += w * n_names
            metrics["max_datapath_width"] = max(metrics["max_datapath_width"], w)

        # ---- 2. Arithmetic: separate cheap from nonlinear ----------------
        # Find every *, /, % and inspect its operands. Both operands being
        # non-constant identifiers  => genuine nonlinear op (expensive).
        # multiply/divide by a literal or a power-of-two shift is cheap.
        ident = r'[A-Za-z_]\w*'
        for op in self.NONLINEAR_OPS:
            pat = re.compile(r'(' + ident + r'(?:\s*\[[^\]]*\])?)\s*\%s\s*(' % op + ident + r'(?:\s*\[[^\]]*\])?|\d+)')
            for mt in pat.finditer(content):
                lhs, rhs = mt.group(1).strip(), mt.group(2).strip()
                rhs_is_const = bool(re.match(r'^\d', rhs))
                if not rhs_is_const:
                    metrics["nonlinear_arith_ops"] += 1
                    metrics["nonlinear_detail"].append(f"{lhs} {op} {rhs}")
                else:
                    metrics["cheap_arith_ops"] += 1

        for op in self.CHEAP_OPS:
            metrics["cheap_arith_ops"] += content.count(op)

        # ---- 3. Control / metadata ---------------------------------------
        for kw in self.CONTROL_KEYWORDS:
            metrics["control_ops"] += len(re.findall(r'\b' + kw + r'\b', content))

        metrics["sv_interfaces"] = len(re.findall(r'\binterface\b', content)) // 2
        metrics["sv_structs"] = len(re.findall(r'\bstruct\b', content))
        metrics["sva_assertions"] = len(
            re.findall(r'\b(assert|assume|cover)\s+property\b', content))

        for pat in [r'\brvvi_\w+\b', r'\bRVVI\b', r'\brvfi_\w+\b', r'\bRVFI\b']:
            metrics["rvvi_hooks"] += len(re.findall(pat, content))

        return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_core.py <verilog_file>")
        sys.exit(1)
    data = VerilogMetricsParser().parse_module(sys.argv[1])
    print(json.dumps(data, indent=4))
