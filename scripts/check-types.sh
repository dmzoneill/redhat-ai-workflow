#!/bin/bash
# Type-check all tool modules
# Usage: ./scripts/check-types.sh [module_name]
#   ./scripts/check-types.sh              # Check all modules
#   ./scripts/check-types.sh aa-git       # Check specific module

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check specific module or all
if [ -n "$1" ]; then
    MODULES=("$1")
else
    MODULES=($(ls -d "$PROJECT_ROOT"/tool_modules/aa-*/ 2>/dev/null | xargs -n1 basename))
fi

echo -e "${YELLOW}Type-checking modules with mypy...${NC}\n"

total=0
passed=0
failed=0

for module in "${MODULES[@]}"; do
    module_path="$PROJECT_ROOT/tool_modules/$module"

    if [ ! -d "$module_path/src" ]; then
        echo -e "${YELLOW}⊘ $module${NC} - No src/ directory, skipping"
        continue
    fi

    total=$((total + 1))
    echo -e "${YELLOW}Checking $module...${NC}"

    cd "$module_path"
    # Set MYPYPATH to include project root and server directory
    export MYPYPATH="$PROJECT_ROOT:$PROJECT_ROOT/server:$PROJECT_ROOT/tool_modules"
    if mypy --package src --explicit-package-bases 2>&1; then
        echo -e "${GREEN}✓ $module passed${NC}\n"
        passed=$((passed + 1))
    else
        echo -e "${RED}✗ $module failed${NC}\n"
        failed=$((failed + 1))
    fi
    cd "$PROJECT_ROOT"
done

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "Total: $total | ${GREEN}Passed: $passed${NC} | ${RED}Failed: $failed${NC}"

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}All type checks passed!${NC}"
    exit 0
else
    echo -e "${RED}Some type checks failed.${NC}"
    exit 1
fi
