# Chat Command Analysis - Direct CLI Usage Across AI Assistants

**Generated:** 2026-02-06
**Sources Analyzed:**
- Cursor Chat SQLite: `~/.cursor/chats/*/store.db` (1 database)
- Claude Code Sessions: `~/.claude/projects/*/*.jsonl` (2,068 sessions, 17 projects)
- Gemini CLI Sessions: `~/.gemini/tmp/*/chats/session-*.json` (144 sessions)
- Codex Sessions: `~/.codex/sessions/**/*.jsonl` (27 sessions)

## Summary

| Metric | Count |
|--------|-------|
| **Total commands found** | 8,740 |
| **Unique commands** | 6,884 |
| **Commands from Claude Code** | 7,870 (90%) |
| **Commands from Gemini CLI** | 770 (9%) |
| **Commands from Codex** | 64 (1%) |
| **Commands from Cursor** | 36 (<1%) |

## Commands by Category (Priority Order for MCP Conversion)

### Priority 1: High-Volume, High-Value MCP Conversions

These are frequently used directly and would benefit most from MCP tool wrapping.

#### 1. `curl` / HTTP Requests (336 instances, 287 unique)
**Current:** Direct `curl` commands for API calls
**Proposed MCP Tool:** `http_request` / `api_call`

Top patterns:
- `curl -X POST http://localhost:8080/v1/chat/completions` (7x)
- `curl http://localhost:8080/health` (4x)
- `curl -H "Authorization: Bearer $(cat ~/.cache/redhatter/auth_token)"` (4x)
- `curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN"` (3x)
- `curl -sk -X POST "${SPLUNK_URL}"` (2x)

**Recommendation:** Create `http_request` MCP tool with:
- Method (GET/POST/PUT/DELETE)
- URL
- Headers (auto-inject auth tokens from credential store)
- Body (JSON/form)
- Response parsing (jq-like filtering)

#### 2. `git` Commands (1,115 instances, 819 unique)
**Current:** Direct git CLI
**Proposed MCP Tools:** Already have `git_core` module, but these are bypassed

Top patterns bypassing MCP:
- `git commit -m "$(cat <<'EOF'` (53x) - Claude Code uses bash directly
- `git log --oneline -5` (23x)
- `git status --short` (17x)
- `git add -A && git commit` (16x)
- `git push origin main` (6x)
- `git push --force-with-lease` (5x)
- `git checkout main` (7x)
- `git diff` (4x)

**Recommendation:** Ensure Claude Code and Gemini use existing git MCP tools. May need a wrapper/hook.

#### 3. `glab` / `gh` - GitLab/GitHub CLI (272 instances, 243 unique)
**Current:** Direct CLI calls
**Proposed MCP Tools:** `gitlab_mr_view`, `github_run_list`, `github_run_view`

Top patterns:
- `glab mr view 1483 --repo automation-analytics/automation-analytics-backend` (7x)
- `gh run list --repo dmzoneill/DFakeSeeder --limit 1` (4x)
- `glab mr diff 1483` (3x)
- `gh run view <id> --log` (1x)
- `gh auth status` (2x)
- `glab auth status` (2x)

**Recommendation:** Expand `gitlab_basic` module with `gitlab_mr_diff`, and create `github_basic` module with `github_run_list`, `github_run_view`, `github_run_logs`.

#### 4. `systemctl` / Service Management (596 instances)
**Current:** Direct systemctl commands
**Proposed MCP Tool:** `systemctl_manage`

Top patterns:
- `systemctl --user restart redhatter` (23x)
- `systemctl daemon-reload` (31x)
- `sudo systemctl daemon-reload` (18x)
- `systemctl --user status redhatter` (12x)
- `sudo systemctl restart ollama-nvidia` (11x)
- `systemctl restart sshd` (10x)

**Recommendation:** Create `systemctl` MCP tool with unit name, action (start/stop/restart/status/enable/disable), and --user flag.

#### 5. `ssh` / Remote Commands (802 instances)
**Current:** Direct SSH commands to VMs
**Proposed MCP Tool:** `ssh_exec`

Top patterns:
- `ssh root@192.168.122.100 '<command>'` (81x)
- `ssh -o StrictHostKeyChecking=no root@192.168.122.100` (39x)
- `sshpass -p "1" ssh root@192.168.122.147` (31x)

**Recommendation:** Create `ssh_exec` MCP tool with host, user, command, and optional password/key. Pre-configure known hosts.

### Priority 2: Medium-Volume Conversions

#### 6. `pytest` / Test Running (1,133 instances)
**Current:** Direct pytest commands
**Proposed MCP Tool:** `run_tests`

Top patterns:
- `python -m pytest tests/<file> -v` (many variations)
- `python -m pytest --cov=tool_modules --cov-report=json` (4x)
- Test-specific file runs

**Recommendation:** Enhance existing test MCP tools or create `run_tests` with file, markers, coverage options.

#### 7. `flake8` / `mypy` / `ruff` / Linting (1,266 instances)
**Current:** Direct linting commands
**Proposed MCP Tool:** `run_lint`

Top patterns:
- `flake8 --select=E402 --exclude=.venv,.claude,extensions,tests` (8x)
- `flake8 <file> --select=C901` (7x)
- `mypy <file>` (many)

**Recommendation:** Create unified `run_lint` MCP tool with linter selection, file targeting, and rule filtering.

#### 8. `make` / Build Commands (407 instances)
**Current:** Direct make targets
**Proposed MCP Tool:** `run_make`

Top patterns:
- `make build` (5x)
- `make bundle validate` (3x)
- `make quality-dashboard` (2x)

**Recommendation:** Create `run_make` MCP tool with target and working directory.

#### 9. `kubectl` / `oc` / Kubernetes (191 instances)
**Current:** Direct k8s CLI (often bypassing existing MCP tools)
**Proposed:** Already have `k8s_basic` module

Top patterns:
- `kubectl get pods -n <namespace>` (multiple)
- `kubectl --kubeconfig=~/.kube/config.e` (multiple)
- `oc get/describe/logs` (various)

**Recommendation:** Ensure k8s MCP tools are used. May need better discoverability.

#### 10. `docker` / `podman` / Container Operations (79 instances)
**Current:** Direct container CLI
**Proposed MCP Tool:** `container_run`, `container_build`, `container_logs`

Top patterns:
- `docker run --rm` (2x)
- `docker compose up/down` (multiple)
- `podman network create` (2x)
- `podman logs` (2x)

**Recommendation:** Create container MCP module with run, build, compose, logs, images operations.

### Priority 3: Lower-Volume but Valuable Conversions

#### 11. `journalctl` / Log Viewing (266 instances)
**Proposed MCP Tool:** `journal_logs` - unit, lines, follow, since/until

#### 12. `sudo virsh` / VM Management (multiple)
**Proposed MCP Tool:** `vm_manage` - list, start, stop, destroy, console

#### 13. `dnf` / Package Installation (102 instances)
**Proposed MCP Tool:** `package_install` - package name, --yes flag

#### 14. `pipenv` / Python Environment (115 instances)
**Proposed MCP Tool:** `pipenv_run` - command, lock, install

#### 15. `jq` / JSON Processing (33 instances)
**Proposed MCP Tool:** `json_query` - input, jq expression

#### 16. `openssl` / Certificate Operations (6 instances)
**Proposed MCP Tool:** `ssl_check` - host, port, cert info

#### 17. `bitwarden` (`bw`) / Credential Management
**Proposed MCP Tool:** `credential_get` - item name, field

#### 18. `gcloud` / GCP Operations (8 instances)
**Proposed MCP Tool:** `gcloud_exec` - service, command

## Proposed New MCP Tool Modules

| Module | Tools | Priority | Est. Commands Covered |
|--------|-------|----------|----------------------|
| `http_basic` | `http_get`, `http_post`, `http_request`, `api_health_check` | P1 | 336 |
| `system_basic` | `systemctl_manage`, `journal_logs`, `ssh_exec`, `vm_manage` | P1 | 1,664 |
| `github_basic` | `github_run_list`, `github_run_view`, `github_run_logs`, `github_auth_status` | P1 | 139 |
| `lint_basic` | `run_flake8`, `run_mypy`, `run_ruff`, `run_lint` | P2 | 1,266 |
| `test_basic` | `run_pytest`, `run_coverage` | P2 | 1,133 |
| `container_basic` | `container_run`, `container_build`, `compose_up`, `compose_down` | P2 | 79 |
| `package_basic` | `dnf_install`, `pip_install`, `pipenv_run` | P3 | 313 |
| `data_basic` | `json_query`, `yaml_query`, `base64_encode` | P3 | 45 |
| `credential_basic` | `bw_get`, `pass_show`, `ssl_check` | P3 | 21 |
| `cloud_basic` | `gcloud_exec`, `aws_exec` | P3 | 10 |

## Existing MCP Modules Being Bypassed

These modules already exist but commands are still run directly:

| Module | Direct CLI Count | Likely Reason |
|--------|-----------------|---------------|
| `git_core/basic` | 1,115 | Claude Code uses Bash tool, not MCP |
| `k8s_basic` | 191 | Not always loaded; kubectl habit |
| `bonfire_basic` | 65 | Sometimes faster to use CLI directly |
| `gitlab_basic` | 105 | Missing some operations (mr diff) |
| `jira_core` | 28 | Some operations not available |

## Next Steps

1. **Create `http_basic` module** - Covers 336 curl commands
2. **Create `system_basic` module** - Covers 1,664 system commands
3. **Create `github_basic` module** - Covers 139 gh commands
4. **Expand `gitlab_basic`** - Add `mr_diff` and other missing operations
5. **Create `lint_basic` module** - Covers 1,266 linting commands
6. **Create `test_basic` module** - Covers 1,133 test commands
7. **Ensure Claude Code/Gemini use MCP tools instead of raw Bash** for git, k8s, etc.

## Analysis Script

The analysis was performed by `scripts/analyze_chat_commands.py` which processes:
- Cursor SQLite chat databases (blobs table)
- Claude Code JSONL session files (2,068 sessions across 17 projects)
- Gemini CLI JSON session files (144 sessions)
- Codex JSONL session/history files (27 sessions)

Full JSON report: `/tmp/chat_commands_report.json`
