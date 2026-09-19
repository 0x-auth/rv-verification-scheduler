# RV Verification Scheduler

An automated Pre-Compile Metrics Linter and Static Verification Router for RISC-V RTL architectures. This engine evaluates hardware blocks prior to test plan execution to predict compute complexity limits, prevent state space explosion bottlenecks, and generate deterministic EDA tool recipes.

## The Industry Problem

Pre-silicon hardware validation is structurally constrained by the mathematical asymmetry between core realization and correctness checking (**P vs. NP Complexity Asymmetry**). Exploring valid design configurations across a sprawling combinatorial space is an NP-hard problem, whereas verifying isolated execution boundaries remains bounded by polynomial parameters.

Traditional EDA workflows push verification checks deep into the late design cycle right before physical fabrication points-of-no-return (tape-out). When hardware teams implement custom instruction subsets or microarchitectural extensions to an open-source **RISC-V ISA** layout, the verification boundaries expand infinitely. Teams exhaust weeks manually partitioning logic spaces:
1. Running **Formal Verification Engine Model Checkers** over complex structures that inevitably experience catastrophic memory timeout bounds (**State Space Explosion**).
2. Routing pure control frameworks to standard **Simulation Suites**, leaving highly dangerous edge-case bugs completely unchecked.

## The Solution Strategy

This tool addresses structural bottlenecks directly inside the Continuous Integration (CI/CD) pre-compile boundary phase. The engine statically parses incoming Verilog and SystemVerilog files, extracts dense layout parameters, and automatically computes an optimal routing plan:

*   **Formal Verification Track Optimization:** Isolates pure control tracking states, condition structures, and explicit decoupled validation hooks (**RISC-V Verification Interface / RVVI** specifications). These blocks are routed to formal tools for 100% complete mathematical coverage.
*   **Target-Guided Simulation Track Mapping:** Flags high-density math matrices and arithmetic register arrays that naturally choke model checkers. The engine automatically bypasses the formal tool to generate high-speed compilation scripts for target simulators.

## Metric Evaluation Profile Matrix

The classification engine acts as a pre-lint validator by measuring targeted structural vectors:
*   `control_weight`: Density counts of state blocks (`always_ff`, `always_comb`, branching statements).
*   `arithmetic_weight`: Combinatorial calculation depth markers (`+`, `-`, `*`, `/`, shifts).
*   `state_depth`: Active logical memory space indicators (`reg`, `logic` bounds).
*   `rvvi_compliance_hooks`: Architectural interface traces verifying compatibility with standard compliance networks.

## Repository Layout Configuration

```text
rv-verification-scheduler/
├── parse_core.py             # RTL Static Metric Parser & Feature Extractor
├── ttc                       # Predictive Execution Classifier & Script Router
├── test_pipeline_harness.sh  # Automated Batch Analysis Pipeline Wrapper
├── LICENSE                   # Apache 2.0 Open Source Agreement Layout
├── README.md                 # Technical Specification Manual Documentation
└── .gitignore                # System and EDA Cache Tracking Block Filter
```

## Quick Start Pipeline Execution

Run the unified batch analysis automation wrapper locally to evaluate all system file modules across your active workspace path:

```bash
./test_pipeline_harness.sh
```

### Manual Engine Evaluation Piping

To stream individual functional modules directly through the feature calculation core to generate customized tool verification compilation recipes:

```bash
python3 parse_core.py sample_advanced.sv | python3 ttc
```

## License

This architecture tool framework is explicitly released under the parameters of the **Apache License 2.0**. For complete structural clause provisions, refer to the accompanying `LICENSE` file template.
