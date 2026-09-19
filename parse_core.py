import re
import sys
import json

class VerilogMetricsParser:
    def __init__(self):
        self.control_keywords = ['always', 'if', 'else', 'case', 'endcase', 'always_ff', 'always_comb']
        self.arithmetic_operators = ['+', '-', '*', '/', '%', '<<', '>>']
        
    def parse_module(self, file_path):
        try:
            with open(file_path, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Error: File {file_path} not found.", file=sys.stderr)
            sys.exit(1)
            
        # Strip comments
        content = re.sub(r'//.*?\n', '\n', content)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        metrics = {
            "module_name": "unknown",
            "control_density": 0,
            "arithmetic_density": 0,
            "state_registers": 0,
            "sv_interfaces": 0,
            "sv_structs": 0,
            "sva_assertions": 0,
            "rvvi_trace_interfaces": 0,
            "assigned_targets": set()
        }
        
        # Extract module name
        module_match = re.search(r'\bmodule\s+(\w+)', content)
        if module_match:
            metrics["module_name"] = module_match.group(1)
        
        # Count standard logic registers
        registers = re.findall(r'\b(reg|logic)\b', content)
        metrics["state_registers"] = len(registers)
        
        # Advanced SystemVerilog Structural Tracking
        metrics["sv_interfaces"] = len(re.findall(r'\binterface\b', content)) // 2
        metrics["sv_structs"] = len(re.findall(r'\bstruct\b', content))
        metrics["sva_assertions"] = len(re.findall(r'\b(assert|assume|cover)\s+property\b', content))
        
        # Explicit RVVI Decoupled Verification Interface Rule Tracking
        rvvi_patterns = [r'\brvvi_\w+\b', r'\bRVVI\b', r'\bvh_inst\b']
        for pattern in rvvi_patterns:
            metrics["rvvi_trace_interfaces"] += len(re.findall(pattern, content))
        
        # Line-by-line metrics accumulation
        lines = content.split('\n')
        for line in lines:
            for kw in self.control_keywords:
                metrics["control_density"] += len(re.findall(r'\b' + kw + r'\b', line))
                
            for op in self.arithmetic_operators:
                metrics["arithmetic_density"] += line.count(op)
                
            assign_match = re.search(r'\b(?:assign\s+)?(\w+)\s*<=?=', line)
            if assign_match:
                metrics["assigned_targets"].add(assign_match.group(1))
                
        metrics["assigned_targets"] = list(metrics["assigned_targets"])
        return metrics

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_core.py <verilog_file>")
        sys.exit(1)
    parser = VerilogMetricsParser()
    data = parser.parse_module(sys.argv[1])
    print(json.dumps(data, indent=4))
