#!/bin/bash
# Batch-run the verification router over every .v/.sv in this folder.

chmod +x parse_core.py 2>/dev/null

echo "RTL verification routing"
echo "========================"
echo ""

find . -maxdepth 1 \( -name "*.v" -o -name "*.sv" \) ! -name ".*" | sort | while read -r f; do
    name=$(basename "$f")
    echo "### $name"
    python3 parse_core.py "$name" | python3 ttc
    echo ""
done
