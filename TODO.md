# 📋 Code Quality TODO

Generated: 2025-12-27

## Summary

| Category | Issues | Status |
|----------|--------|--------|
| Formatting (Black/isort) | ~30 files | 🔴 Pending |
| Flake8 Errors | 1,602 | 🔴 Pending |
| YAML Lint | 1,772 | 🟡 Low Priority |
| Test Coverage | 21% → 60% | 🔴 Pending |
| Large File Refactor | 1 file | 🟡 Future |

---

## 🔴 Priority 1: Auto-Fixable Issues

### 1.1 Black Formatting
- [ ] `mcp-servers/aa-common/src/__init__.py`
- [ ] `mcp-servers/aa-jira/src/__init__.py`
- [ ] `mcp-servers/aa-git/src/__init__.py`
- [ ] `mcp-servers/aa-alertmanager/src/__init__.py`
- [ ] `mcp-servers/aa-appinterface/src/__init__.py`
- [ ] `mcp-servers/aa-gitlab/src/__init__.py`
- [ ] `mcp-servers/aa-common/src/web/__init__.py`
- [ ] `mcp-servers/aa-bonfire/src/__init__.py`
- [ ] `mcp-servers/aa-google-calendar/src/__init__.py`
- [ ] `mcp-servers/aa-k8s/src/__init__.py`
- [ ] `mcp-servers/aa-kibana/src/__init__.py`
- [ ] `mcp-servers/aa-konflux/src/__init__.py`
- [ ] `mcp-servers/aa-prometheus/src/__init__.py`
- [ ] `mcp-servers/aa-quay/src/__init__.py`
- [ ] `mcp-servers/aa-slack/src/__init__.py`
- [ ] `mcp-servers/aa-common/src/config.py`

### 1.2 isort Import Sorting
- [ ] `scripts/slack_control.py`
- [ ] `scripts/claude_agent.py`
- [ ] `scripts/slack_daemon.py`
- [ ] `scripts/slack_dbus.py`
- [ ] `scripts/integration_test.py`
- [ ] `scripts/common/jira_utils.py`
- [ ] `scripts/common/parsers.py`
- [ ] `mcp-servers/aa-slack/src/server.py`
- [ ] `mcp-servers/aa-gitlab/src/tools.py`
- [ ] `mcp-servers/aa-gitlab/src/server.py`
- [ ] `mcp-servers/aa-gitlab/src/__init__.py`
- [ ] `mcp-servers/aa-bonfire/src/tools.py`

---

## 🔴 Priority 2: Flake8 Issues (1,602 total)

### 2.1 Line Too Long - E501 (1,307 instances)
Top offenders:
- [ ] `scripts/slack_dbus.py` - 6 lines
- [ ] `scripts/slack_test.py` - 7 lines
- [ ] Multiple MCP server files

### 2.2 Unused Imports - F401 (65 instances)
- [ ] Scan and remove unused imports across all modules

### 2.3 Too Many Blank Lines - E303 (212 instances)
- [ ] Clean up extra blank lines

### 2.4 Unused Variables - F841 (12 instances)
- [ ] Remove or use assigned variables

### 2.5 Blank Line Issues - E302 (5 instances)
- [ ] Fix expected blank lines

---

## 🟡 Priority 3: Code Quality

### 3.1 Bare Exception Handlers (153 instances)
Files to review:
- [ ] `mcp-servers/aa-workflow/src/tools.py` (28)
- [ ] `mcp-servers/aa-slack/src/tools.py` (19)
- [ ] `mcp-servers/aa-google-calendar/src/tools.py` (15)
- [ ] `scripts/slack_daemon.py` (10)
- [ ] `mcp-servers/aa-common/src/utils.py` (7)
- [ ] `scripts/claude_agent.py` (7)
- [ ] `mcp-servers/aa-slack/src/listener.py` (6)
- [ ] `mcp-servers/aa-common/src/debuggable.py` (5)
- [ ] `mcp-servers/aa-common/src/server.py` (5)
- [ ] `mcp-servers/aa-appinterface/src/tools.py` (5)

### 3.2 Debug Print Statements (221 instances)
Review and categorize:
- [ ] `scripts/slack_daemon.py` (64) - CLI tool, may be intentional
- [ ] `scripts/integration_test.py` (49) - Test output, may be intentional
- [ ] `scripts/slack_test.py` (37) - Test output
- [ ] `scripts/skill_test_runner.py` (31) - Test output
- [ ] `scripts/slack_control.py` (27) - CLI tool

### 3.3 TODO Comments (6 instances)
- [ ] `scripts/slack_dbus.py:353` - Store thread_ts in record
- [ ] `scripts/integration_test.py:353` - Actually call tool via MCP

---

## 🟡 Priority 4: Test Coverage (21% → 60%)

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

## ✅ Completed

- [x] Documentation structure (docs/)
- [x] Cursor commands (35 commands)
- [x] README comprehensive update
- [x] Code quality analysis

---

## Progress Tracking

| Date | Action | Files Changed |
|------|--------|---------------|
| 2025-12-27 | Initial analysis | - |
| | | |

---

## Commands

```bash
# Auto-fix formatting
cd ~/src/redhat-ai-workflow
black mcp-servers/ scripts/
isort mcp-servers/ scripts/

# Check flake8
flake8 --exclude=.venv mcp-servers/ scripts/

# Run tests with coverage
pytest --cov=mcp-servers --cov-report=html
```

