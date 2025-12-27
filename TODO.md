# 📋 Code Quality TODO

Generated: 2025-12-27
Last Updated: 2025-12-27

## Summary

| Category | Before | After | Status |
|----------|--------|-------|--------|
| Formatting (Black/isort) | ~30 files | 0 | ✅ Fixed |
| Unused Imports (F401) | 65 | 0 | ✅ Fixed |
| Unused Variables (F841) | 12 | 0 | ✅ Fixed |
| Bare Except (E722) | 10 | 0 | ✅ Fixed |
| Syntax Errors (E999) | 1 | 0 | ✅ Fixed |
| Ambiguous Variables (E741) | 16 | 0 | ✅ Fixed |
| Trailing Whitespace (W291/W293) | 37 | 0 | ✅ Fixed |
| Duplicate Import (F811) | 1 | 0 | ✅ Fixed |
| Invalid Escape (W605) | 1 | 0 | ✅ Fixed |
| Line Too Long (E501) | 1,191 | 1,177 | 🟡 Style |
| F-string No Placeholder (F541) | 50 | 46 | 🟡 Style |
| Import Not at Top (E402) | 48 | 48 | ⚪ Intentional |
| Test Suite | 0 | 54 tests | ✅ Added |
| Test Coverage | 0% | 4% (core: 25%) | 🟢 Started |

---

## ✅ Completed

### 2025-12-27

- [x] **Black formatting** - Applied to all 68 files
- [x] **isort imports** - All imports sorted correctly
- [x] **Unused imports (F401)** - Removed 65 instances
- [x] **Unused variables (F841)** - Removed 12 instances
- [x] **Bare except handlers (E722)** - All 10 replaced with specific types
- [x] **Syntax errors (E999)** - Fixed indentation in appinterface
- [x] **Ambiguous variables (E741)** - Renamed `l` → `ln` in 16 places
- [x] **Trailing whitespace (W291/W293)** - Removed from all files
- [x] **Duplicate import (F811)** - Fixed in claude_agent.py
- [x] **Invalid escape sequence (W605)** - Fixed in parsers.py
- [x] **D-Bus type annotations (F821)** - Added noqa for slack_dbus.py
- [x] **Test suite** - Added 54 tests across 5 test modules
- [x] Documentation structure (docs/)
- [x] Cursor commands (35 commands)
- [x] README comprehensive update
- [x] Code quality analysis

---

## 🟡 Remaining Style Issues (Low Priority)

### E501: Line Too Long (1,177 instances)
These are style preferences - lines slightly over 79 chars.
Options:
1. Configure flake8 for 100 or 120 char limit
2. Add `.flake8` config file

### F541: F-string Without Placeholder (46 instances)
These work correctly but have minor overhead.
Change `f"text"` to `"text"` when no `{}` placeholders.

### E402: Import Not at Top (48 instances)
These are intentional - path setup requires imports after sys.path modifications.

---

## 🟢 Test Coverage Progress

### Current Coverage (54 tests)
- **mcp-servers/aa-common/src/config.py**: 16%
- **mcp-servers/aa-common/src/utils.py**: 25%
- **scripts/common/jira_utils.py**: 58%

### Tests by Module
| Module | Tests | Status |
|--------|-------|--------|
| test_agents.py | 8 | ✅ |
| test_config.py | 6 | ✅ |
| test_jira_utils.py | 16 | ✅ |
| test_skills.py | 9 | ✅ |
| test_utils.py | 15 | ✅ |

### Future: High-Value Test Targets
- [ ] `mcp-servers/aa-workflow/src/tools.py` - Skill execution
- [ ] `mcp-servers/aa-git/src/tools.py` - Git operations
- [ ] `scripts/common/parsers.py` - Output parsing
- [ ] `mcp-servers/aa-common/src/agent_loader.py` - Agent loading

---

## 🟢 Future: Refactoring

### Split Large Files
`mcp-servers/aa-workflow/src/tools.py` (3,005 lines) into:
- [ ] `skill_engine.py` - Skill execution logic
- [ ] `memory_tools.py` - Memory operations
- [ ] `agent_tools.py` - Agent management
- [ ] `session_tools.py` - Session management
- [ ] `workflow_tools.py` - Workflow utilities

---

## Progress Tracking

| Date | Action | Files Changed |
|------|--------|---------------|
| 2025-12-27 | Initial analysis | - |
| 2025-12-27 | Black + isort formatting | 68 files |
| 2025-12-27 | Fix unused imports (MCP) | 26 files |
| 2025-12-27 | Fix unused imports (scripts) | 7 files |
| 2025-12-27 | Fix bare except handlers | 6 files |
| 2025-12-27 | Fix misc flake8 issues | 4 files |
| 2025-12-27 | Fix indentation error | 1 file |
| 2025-12-27 | Fix trailing whitespace + E741 | 10 files |
| 2025-12-27 | Add test suite | 7 files |

---

## Quick Commands

```bash
# Check current status
cd ~/src/redhat-ai-workflow
flake8 --exclude=.venv --statistics mcp-servers/ scripts/

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=mcp-servers --cov=scripts --cov-report=html

# Configure flake8 for longer lines (optional)
echo "[flake8]
max-line-length = 100
exclude = .venv
ignore = E402" > .flake8
```
