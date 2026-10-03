#!/bin/bash
# Batch validate all .xfy files

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "================================================================================"
echo "BATCH VALIDATION - XFY Scripts"
echo "================================================================================"
echo ""

PASSED=0
FAILED=0
TOTAL=0

SEARCH_DIR="samples"
if [ ! -d "$SEARCH_DIR" ]; then
    SEARCH_DIR="tests"
fi

while IFS= read -r file; do
    [ -z "$file" ] && continue
    TOTAL=$((TOTAL + 1))
    echo "[$TOTAL] Testing: $file"

    # Run validation and capture result
    if timeout 120 python3 tools/validate_xfy.py --blender "$file" 2>&1 | grep -q "ALL CHECKS PASSED"; then
        echo "    ✓ PASSED"
        PASSED=$((PASSED + 1))
    else
        echo "    ✗ FAILED"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done < <(find "$SEARCH_DIR" -name "*.xfy" -type f 2>/dev/null | sort)

echo "================================================================================"
echo "SUMMARY"
echo "================================================================================"
echo "Total files: $TOTAL"
echo "Passed:      $PASSED"
echo "Failed:      $FAILED"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "🎉 All tests passed!"
    exit 0
else
    echo "⚠️  Some tests failed"
    exit 1
fi
