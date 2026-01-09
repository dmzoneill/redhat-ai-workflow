#!/bin/bash
# Run GitHub Super-Linter locally via Docker
# This matches the CI linting done in GitHub Actions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

printf '%b%s%b\n' "${CYAN}" "Running Super-Linter..." "${NC}"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    printf '%b%s%b\n' "${RED}" "❌ Docker is not installed or not in PATH" "${NC}"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    printf '%b%s%b\n' "${RED}" "❌ Docker daemon is not running" "${NC}"
    exit 1
fi

# Get the repo root (works whether called from repo root or subdirectory)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

printf '%b%s%s%b\n' "${CYAN}" "Linting: " "${REPO_ROOT}" "${NC}"

# Run Super-Linter with slim image (fewer linters, faster)
# Focus on linters that work well with project defaults
# Use LINTER_RULES_PATH=. to load config files from workspace root
docker run --rm \
    -e RUN_LOCAL=true \
    -e DEFAULT_BRANCH=main \
    -e VALIDATE_ALL_CODEBASE=true \
    -e LINTER_RULES_PATH=. \
    -e VALIDATE_PYTHON_FLAKE8=true \
    -e VALIDATE_YAML=true \
    -e VALIDATE_JSON=true \
    -e VALIDATE_GITHUB_ACTIONS=true \
    -e FILTER_REGEX_EXCLUDE="(\.git|node_modules|__pycache__|\.venv|venv|\.mypy_cache|extensions/|\.super-linter).*" \
    -e LOG_LEVEL=NOTICE \
    -v "${REPO_ROOT}":/tmp/lint \
    ghcr.io/super-linter/super-linter:slim-latest

printf '%b%s%b\n' "${GREEN}" "✅ Super-Linter passed" "${NC}"
