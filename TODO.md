# 📋 Code Quality TODO

Generated: 2025-12-27
Last Updated: 2025-12-27

## Summary

| Category | Issues | Status |
|----------|--------|--------|
| Formatting (Black/isort) | ~30 files | ✅ Fixed |
| Unused Imports (F401) | 65 | ✅ Fixed |
| Unused Variables (F841) | 12 | ✅ Fixed |
| Line Too Long (E501) | 1,191 | 🟡 Low Priority |
| Bare Except (E722) | 10 | 🟡 Review |
| Test Coverage | 21% → 60% | 🔴 Pending |
| YAML Lint | 1,772 | 🟡 Low Priority |
| Large File Refactor | 1 file | 🟡 Future |

---

## ✅ Completed

### 2025-12-27

- [x] **Black formatting** - Applied to all 68 files
- [x] **isort imports** - All imports sorted correctly
- [x] **Unused imports (F401)** - Removed 65 instances across all modules
- [x] **Unused variables (F841)** - Removed 12 instances
- [x] Documentation structure (docs/)
- [x] Cursor commands (35 commands)
- [x] README comprehensive update
- [x] Code quality analysis

---

## 🟡 Priority 3: Remaining Issues

### 3.1 Line Too Long - E501 (1,191 instances)
These are style issues, not functional problems. Most lines are slightly over 79 chars.
Consider updating flake8 config to allow 120 chars.

### 3.2 Bare Exception Handlers - E722 (10 instances)
Review these for more specific exception handling:
- [ ] `mcp-servers/aa-workflow/src/tools.py`
- [ ] `mcp-servers/aa-common/src/server.py`
- [ ] Scripts

### 3.3 Other Style Issues
| Issue | Count | Notes |
|-------|-------|-------|
| E402 (import not at top) | 48 | Often intentional (path setup) |
| F541 (f-string no placeholders) | 50 | Should review |
| E741 (ambiguous variable) | 16 | Usually `l` → `line` |
| W291/W293 (whitespace) | 37 | Auto-fixable |

---

## 🔴 Priority 4: Test Coverage (21% → 60%)

### 4.1 Core Modules to Test
- [ ] `mcp-servers/aa-common/src/utils.py` - Shared utilities
- [ ] `mcp-servers/aa-workflow/src/tools.py` - Skill execution
- [ ] `mcp-servers/aa-common/src/config.py` - Configuration
- [ ] `mcp-servers/aa-common/src/agent_loader.py` - Agent loading

### 4.2 Test Infrastructure
- [ ] Create `tests/` directory structure
- [ ] Add pytest configuration
- [ ] Add test fixtures for common scenarios
- [ ] Add CI integration

---

## 🟢 Priority 5: Refactoring (Future)

### 5.1 Split Large Files
`mcp-servers/aa-workflow/src/tools.py` (3,005 lines) into:
- [ ] `skill_engine.py` - Skill execution logic
- [ ] `memory_tools.py` - Memory operations
- [ ] `agent_tools.py` - Agent management
- [ ] `session_tools.py` - Session management
- [ ] `workflow_tools.py` - Workflow utilities

### 5.2 YAML Lint (1,772 issues)
Low priority - mostly style issues:
- Trailing spaces
- Line length > 80
- Missing document start `---`

---

## Progress Tracking

| Date | Action | Files Changed |
|------|--------|---------------|
| 2025-12-27 | Initial analysis | - |
| 2025-12-27 | Black + isort formatting | 68 files |
| 2025-12-27 | Fix unused imports (MCP servers) | 26 files |
| 2025-12-27 | Fix unused imports (scripts) | 7 files |

---

## Commands

```bash
# Check current status
cd ~/src/redhat-ai-workflow
flake8 --exclude=.venv --statistics mcp-servers/ scripts/

# Run tests with coverage
pytest --cov=mcp-servers --cov-report=html

# Auto-fix remaining whitespace
autopep8 --in-place --select=W291,W293 mcp-servers/**/*.py scripts/*.py
```
