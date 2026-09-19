#!/bin/bash

# Ensure scripts have proper execution configurations
chmod +x parse_core.py 2>/dev/null

echo "=================================================="
echo "  Executing RTL Verification Structural Analysis  "
echo "=================================================="
echo ""

# Find all Verilog and SystemVerilog files in the current folder, ignoring hidden structures
find . -maxdepth 1 \( -name "*.v" -o -name "*.sv" \) ! -name ".*" | while read -r verilog_file; do
    filename=$(basename "$verilog_file")
    echo "Processing Module File: $filename"
    echo "--------------------------------------------------"
    
    # Run the core validation pipeline execution
    python3 parse_core.py "$filename" | python3 ttc
    
    echo "--------------------------------------------------"
    echo ""
done

echo "=================================================="
echo "  Analysis Complete. All Targets Processed.       "
echo "=================================================="
