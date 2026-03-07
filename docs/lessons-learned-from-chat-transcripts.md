# Lessons Learned from Cursor Chat Transcripts

Extracted by multi-agent inspection of `agent-transcripts/` (13 chats). Transcript IDs are cited as short UUIDs (e.g. [ab56c4b1](ab56c4b1-ce9f-452a-916f-5b4f2379c792)).

---

## 1. Tool / skill failures and fixes

| Lesson | Source | Details |
|--------|--------|---------|
| Jira adapter `view` vs `view-issue` | ab56c4b1 | `memory_ask(…, sources="jira")` failed until adapter called `view-issue` (rh-issue expects that). Fixed in `tool_modules/aa_jira/src/adapter.py`. |
| Closed transition requires Workstream | ab56c4b1 | Transition to **Closed** needs customfield_12319275 (Workstream), sent as array `[{ "id": "..." }]`. jira-creator `set_status_plugin.py` loads issue fields and sends Workstream. |
| Jira delete-comment timeouts | ab56c4b1 | `jira_delete_comment(…, all_comments=True)` can hit 30s timeouts. Run deletes in a loop or increase MCP timeout. |
| `gh_pr_checkout` PR number type | ab56c4b1 | Implementation expected string for PR number; core wrapper now uses `_gh_pr_checkout_impl(str(pr_number), ...)`. |
| GitLab unreachable (VPN) | eb122e20 | gitlab.cee.redhat.com not reachable from agent env. Prepare branches/commits locally; user runs push and MR creation on VPN. |
| app-interface terraform-repo `ref` | 79268cd6 | Validation fails with `'ref' is a required property`. Use **40-char commit SHA**, not branch name. Add e.g. `ref: 6bc292160c8184571900271a0185d621b5e5eab1`. |
| Jira add-link step | 8f9f3863 | In-Jira link to APPSRE-13651 didn’t create; add-link expects different flags. Workaround: add comment with issue and Slack URLs. |

---

## 2. Workflow and process

| Lesson | Source | Details |
|--------|--------|---------|
| Check skills first | ab56c4b1, 7c14de4f | Always check for a matching skill; run via `skill_run` with **inputs as a JSON string** (escape quotes, `\n` for newlines). |
| Use MCP tools, not scripts | ab56c4b1 | Use persona_load, gh_repo_clone, gh_pr_checkout, git_add, git_commit, git_push; do not generate shell scripts for clone/checkout. |
| Refinement flow | ab56c4b1 | Gather epic + children + notes → pull AC/description from Jira (jira_view_issue, no inferring) → build plan → **execute only after user confirms** (delete comments, add comment, transition with Workstream). |
| One SDP per ANSTRAT | ab56c4b1 | One Jira story per SDP; one ANSTRAT → one story. Don’t create two stories for the same ANSTRAT. |
| GDrive via skills | ab56c4b1, 19b759bd, 66797068 | No persona includes aa_gdrive; use **skill** (e.g. `gdrive_fetch_doc` by file_id). Skill engine runs GDrive tools in skill steps. |
| Session / persona | ab56c4b1 | Load correct persona (e.g. developer for Jira, github for clone/PR) so the right MCP tools are available. |
| Skill engine as source of truth | 1e307d93 | Keep skill engine as source of truth; SKILL.md as optional export; invest in evals and discovery. |

---

## 3. Jira

| Lesson | Source | Details |
|--------|--------|---------|
| Child stories | ab56c4b1 | Get children via **jira_search**: `jql="parent = AAP-66639"`, not from single-issue view. |
| Transition to Closed | ab56c4b1 | Always send **Workstream** (customfield_12319275) in transition payload as array `[{ "id": "..." }]`. |
| jira_transition param | b15f1347 | Tool is `jira_transition(issue_key, **status**)`; use `status: "In Progress"`, not `transition`. Skill YAML must match. |
| JQL dates | b15f1347 | Use Jira date functions (e.g. `endOfDay('date')`) or absolute ranges; date arithmetic like `'date' + 1d` can cause HTTP 400. |
| create_jira_issue + add-link | 8f9f3863 | If add-link fails, add a comment with related issue and Slack links so they’re on the issue. |

---

## 4. Git / app-interface

| Lesson | Source | Details |
|--------|--------|---------|
| Commit messages | eb122e20, ab56c4b1 | Include Jira issue key (e.g. AAP-64892) in commit messages for traceability; amend and force-push if needed. |
| app-interface ref after merge | eb122e20 | When updating refs after merge, use **merge commit SHA** from upstream; squash app-interface branch to one commit with that ref. |
| terraform-repo `ref` | 79268cd6 | Schema requires `ref` = **40-char hex commit SHA** (`^([0-9a-f]{40})$`), not short SHA or branch. |

---

## 5. AI rules and docs

| Lesson | Source | Details |
|--------|--------|---------|
| README vs actual files | 7c14de4f | docs/ai-rules README must list **all 11** rule files with correct names (e.g. `60-use-mcp-tools.md` not `60-project-context.md`); include 15, 16, 25, 55. |
| state/shared_context | 7c14de4f | Document keys (current_investigation, last_branch_sync, last_coffee, etc.) and when to read in 25-memory-operations. |
| learned: tool_fixes vs tool_failures | 7c14de4f | tool_fixes = learn_tool_fix + check_known_issues; tool_failures = log for stats/auto-heal; LLM shouldn’t read/write tool_failures directly. |
| Before retrying | 7c14de4f | In 50-auto-debug: call check_known_issues before retrying; document recurring failure modes (auth, network, image/tag). |
| current_work path | 7c14de4f | Document that state/current_work resolves to state/projects/<project>/current_work.yaml; document persona knowledge path (read-only). |
| Intent tables + session_close | 1e307d93 | Keep intent tables in sync with skills; document that session_close is mandatory. |
| 401/VPN in tool_failures | b15f1347 | Treat 401/VPN as transient in docs so agents don’t treat them as product bugs; use memory/learned to drive creator/hygiene behavior. |

---

## 6. Cursor / MCP / environment

| Lesson | Source | Details |
|--------|--------|---------|
| MCP config in Cursor | 0b367547 | Cursor uses **`.cursor/mcp.json`** for project MCP config, not root `.mcp.json`. Keep `.cursor/mcp.json` in sync when changing server command. |
| MCP startup | 0b367547 | Use `.venv/bin/python -m server` for MCP so startup doesn’t run `uv sync` and time out; run `uv sync` once from project root. |

---

## 7. UI / front-end

| Lesson | Source | Details |
|--------|--------|---------|
| Dropdowns in compact headers | 55fa932b | Use `overflow: visible`, `position: relative`, and sufficient `z-index` so open menus aren’t clipped by the content area. |

---

## Summary by category

- **Tool fixes:** Jira adapter, Closed/Workstream, gh_pr_checkout type, app-interface ref, add-link workaround. (Fix tools rather than work around: add_project, Jira Description.)
- **Workflow:** Skill-first, MCP not scripts, refinement confirm-then-execute, GDrive via skills, load correct persona.
- **Jira:** jira_search for children, Workstream for Closed, status not transition, JQL dates.
- **Git:** Jira key in commits, app-interface ref = merge SHA, terraform-repo ref = 40-char SHA.
- **AI rules:** README accuracy, shared_context, tool_fixes vs tool_failures, before-retry check_known_issues, current_work and persona knowledge path.
- **Environment:** Cursor MCP config path, venv for server.
- **UI:** Overflow/z-index for dropdowns.

---

## Applied (2026-03-07)

High-signal lessons were applied as follows:

| Lesson | Applied to |
|--------|------------|
| Jira delete-comment timeout, app-interface ref, jira_add_link fallback | `memory/learned/tool_fixes.yaml` (new entries). Not applied as workarounds: add_project, Jira Description (fix tools instead). |
| Transition to Closed (Workstream) | `docs/ai-rules/55-work-completion.md`. Jira comment practices (delete-all-then-add, etc.) removed—treat as edge case; fix tools rather than document workarounds. |
| GDrive via skills only, no persona | `docs/ai-rules/10-skill-first.md` (Google Drive table), `docs/commands/personas.md` |
| create_jira_issue: when add-link fails | `skills/create_jira_issue.yaml` (step `add_link_fallback_comment`) |
| Cursor MCP config and venv startup | `docs/dev/cursor-mcp.md` (new) |
| app-interface terraform-repo ref = 40-char SHA | `docs/app-interface.md` (new), `docs/ai-rules/40-ephemeral.md` (bullet 5) |

Run `make sync-ai-rules` after editing ai-rules to update `.cursorrules`, `CLAUDE.md`, and `AGENTS.md`.
