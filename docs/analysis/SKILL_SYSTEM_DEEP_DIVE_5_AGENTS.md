# Skill System Deep Dive — 5-Agent Analysis

**Date:** 2026-03-06  
**Method:** Five parallel analysis agents, each focused on a different aspect of the skill system.  
**Scope:** Skill engine, YAML format, discovery/intent/persona, testing, and lifecycle/ecosystem.

---

## Executive Summary

The **skill system** is the main workflow layer of redhat-ai-workflow: YAML-defined, multi-step flows that chain MCP tools, compute blocks, and conditions. Skills are executed by a single **SkillExecutor** (with **TemplateEngineMixin** and **ErrorRecoveryMixin**), discovered via **skill_list()** and intent tables in docs, and tested via a **harness** that mocks all tool calls.

**Findings:**

| Area | Strengths | Gaps / Risks |
|------|-----------|---------------|
| **Engine** | Clear execution loop, tool vs workflow dispatch, session/event logging, auto_heal and retry | FastMCP/tool_discovery coupling; module loading stubs; interactive recovery in async context |
| **YAML** | Rich step types (tool/compute/then/description), Jinja templating, conditions, links | No JSON Schema; validation is code-only; then-block list syntax easy to misuse |
| **Discovery** | skill_list() from filesystem; intent tables in 10-skill-first; bootstrap suggested_skills | No skill_suggest(user_message) MCP tool; no semantic/embedding search; intent tables static |
| **Testing** | Harness mocks all tools; structural/template/condition/regression/execution tests; validate_skills | Regression uses glob not rglob (subdirs); no dedicated ErrorRecoveryMixin tests; coverage not reported |
| **Lifecycle** | skill_run(skill_name, inputs JSON string); chaining via skill_run step or run_skill(); review_pr_multiagent | Tool/persona/skill renames break callers; no static dependency registry |

**Cross-cutting:** Session and memory are wired so skill completions and session_close feed the daily session log; coffee/beer depend on that. Persona integration is via `persona_load` steps (often first or mid-flow). Sub-skills run in-process (workflow tool or compute `run_skill()`); review_pr_multiagent is the only “multi-agent” flow and uses subprocess + threading, not 6 MCP tools.

---

## Agent 1: Skill Engine Internals

### Purpose
Execute multi-step YAML workflows: chain MCP tools, compute blocks, and conditions; handle errors (fail/continue/auto_heal); template args and conditions; log to session and emit events.

### Main Components
- **SkillExecutor** (`skill_engine.py`) — main loop and step dispatch; inherits **ErrorRecoveryMixin** and **TemplateEngineMixin**.
- **TemplateEngineMixin** (`skill_template.py`) — Jinja2/regex templating, `_eval_condition()`, compute blocks (restricted Python with `run_skill`, config, step outputs).
- **ErrorRecoveryMixin** (`skill_error_recovery.py`) — known-issue lookup, auto_heal (VPN/auth), retry, `on_error` handling, soft-failure detection, Layer 5 learning, interactive recovery (compute only).

### Execution Flow
1. **Entry:** `skill_run` → load `skills/<skill_name>.yaml`, validate inputs, get session/workspace from `WorkspaceRegistry.get_for_ctx(ctx)`.
2. **Loop:** For each step: evaluate `condition` (skip if false); emit `step_start`; branch on type:
   - **tool** → template args, `_process_tool_step` → `_exec_tool` (workflow vs module); on failure: known-issue check, auto-fix, retry; handle `on_error`.
   - **compute** → `_exec_compute(code, output_name)` in sandbox; store result in context.
   - **then** → first `return` entry → early exit with templated string.
   - **description** → templated string appended to log.
3. **Post-loop:** Format outputs, emit `skill_complete`, record agent_stats, **append_session_entry** (type `skill`), optional `_extract_and_save_learnings`.

### Tool Dispatch
- **Resolution:** `_get_module_for_tool(tool_name)` → `server.tool_discovery.get_module_for_tool(tool_name)`.
- **Workflow tools** (e.g. `skill_run`, `persona_load`, `memory_ask`): run on current FastMCP server via `self.server.call_tool(tool_name, args)`.
- **Other tools** (e.g. `aa_git`, `aa_jira`): `_load_and_execute_module_tool` builds package stubs, loads module, creates **temporary** FastMCP, registers tools, `await temp_server.call_tool(...)`. Retry after auto-fix uses same temp_server.

### Session / Workspace
- **Source:** `WorkspaceRegistry.get_for_ctx(ctx)` → workspace_uri, active session’s `session_id`, `session_name`.
- **Passed into:** `SkillExecutor(..., workspace_uri, ctx, session_id, session_name, source, source_details)`.
- **Events:** File emitter (`~/.config/aa-workflow/skill_execution.json`) and optional WebSocket (`skill_started`, `step_*`, `skill_completed`/`skill_failed`, `auto_heal_*`).
- **Session log:** At end of `execute()`, `append_session_entry(entry)` with `type: "skill"`, `skill_name`, `result`, `duration_ms`, `session_id` when set → `memory/sessions/YYYY-MM-DD.yaml`.

### Dependencies on server/*
- `server.tool_registry` (registration of skill_list/skill_run).
- `server.utils` (load_config for context).
- `server.tool_discovery` (get_module_for_tool).
- `server.workspace_state` (WorkspaceRegistry).
- `server.usage_pattern_learner` (optional Layer 5).
- `server.websocket_server` (optional events).

### Fragile / Complex Areas
1. **Module loading:** Package stubs and `spec_from_file_location`; relative imports in aa_* must stay consistent.
2. **Two error paths:** Failures in `result["error"]` vs success=True with error text in `result["result"]`; soft-failure detection is a fixed string list.
3. **Interactive recovery:** `run_until_complete(prompt_user_for_action)` in async context can be problematic (nested loop).
4. **Emitter lifecycle:** `set_emitter(None)` by workspace_uri; concurrent runs depend on who last set emitter.
5. **Constants/paths:** SKILLS_DIR, TOOL_MODULES_DIR in constants.py with fallbacks; can drift with scheduler/daemon.

---

## Agent 2: Skill YAML Format and Authoring

### Top-Level Structure
| Key | Required | Description |
|-----|----------|-------------|
| **name** | Yes | Unique skill id (file stem used if missing). |
| **description** | No | Human-readable (markdown). |
| **version** | No | e.g. "1.4". |
| **inputs** | No | List of { name, type?, required?, default?, description? }. |
| **steps** | Yes | Ordered list of steps. |
| **outputs** | No | Named outputs (templated or computed). |
| **links** | No | depends_on, validates, validated_by, chains_to, provides_context_for (metadata only). |
| **defaults** | No | Optional defaults in context. |

### Inputs
- **Validation:** In skill_engine at entry (`_validate_skill_inputs`) and at start of execute (defaults applied, then templated if string with `{{ }}`).
- **Required:** Missing required (and no default) → list of missing names, abort.
- No separate JSON Schema; rules are in code.

### Step Types
- **tool:** `tool`, `args` (templated), `output`, `condition`, `on_error` (fail | continue | auto_heal).
- **compute:** `compute` (Python snippet), `output`; runs in sandbox; result from variable `output_name` or `result`.
- **then:** List of dicts; first dict with key `return` is templated and used as final output; execution stops. Must be `then: [ { return: "..." } ]`, not `then: return`.
- **description:** Templated string appended to log (manual step).

### Conditions and Templating
- **Conditions:** Jinja-style; context = inputs, config, prior step outputs, workspace_uri, today. Rendered then interpreted as bool (true/false/1/0/yes/no or non-empty).
- **Templating:** Same context; Jinja2 with ChainableUndefined and filters (jira_link, mr_link, length); regex fallback for `{{ ... }}`.

### Compute Sandbox
- **Location:** `skill_compute_engine.py` (and mixin in `skill_template.py`).
- **Allowed:** safe_globals (builtins, re, os, pathlib, datetime, json, yaml, etc.); context (inputs as AttrDict, config); `run_skill(skill_name, inputs_dict)` for nested runs; `memory`, `emit_event`, `load_config`, project helpers.
- **Result:** Variable named by `output_name` or `result`, or a return expression.

### Validation
- **Script:** `scripts/validate_skills.py` — structure, tool_names (from tool_discovery manifest), compute_syntax (AST parse), steps_in_outputs, on_error values, variable_chain, inputs have name, unique step names, links structure/references/consistency.
- **Run:** `python scripts/validate_skills.py [--verbose] [--skill NAME]` or `make validate-skills`.

### Authoring Patterns (from real skills)
- **start_work:** Required `issue_key`; persona_load first; compute to resolve repo; mix of tool and compute with conditions on prior outputs.
- **test_mr_ephemeral:** Optional inputs (mr_id, commit_sha, duration, billing, etc.); heavy conditions; persona switches (developer → release → devops); sub-skills (scan_vulnerabilities, mark_mr_ready, notify_team); on_error: auto_heal on GitLab/Quay/Bonfire.
- **jira_hygiene:** Required `issue_key`; compute for project/component; conditional tool steps for fixes; final compute for report.

---

## Agent 3: Skill Discovery, Intent, and Persona Integration

### Skill Listing
- **Tool:** `skill_list()` in skill_engine.py (`_skill_list_impl`).
- **Behavior:** Scans `SKILLS_DIR` for `*.yaml`; for each file reads `name`, `description`, and input **names** only.
- **Returns:** Single TextContent (markdown): per skill, `### name`, description, **Inputs:** comma-separated names or "none". No types, required/default, or example values at list time.

### Intent Mapping
- **Where:** `docs/ai-rules/10-skill-first.md`; synced to `.cursorrules` and `AGENTS.md` via `make sync-ai-rules`.
- **Content:** Decision tree (“check skills first”); “User Says” → Skill + inputs JSON tables (Daily Rituals, Development, Jira, DevOps, Incident, Release, Research, Knowledge, etc.); Intent → Persona fallback.
- **Rule:** Call `skill_run` with **inputs as a JSON string**, not object (e.g. `"{\"issue_key\": \"AAP-12345\"}"`).

### Bootstrap Suggested Skills
- **Location:** `session_tools.py`, `_get_bootstrap_context()`; fixed **skill_map** maps intent → list of skill names (up to ~10 per intent).
- **Usage:** Stored in `bootstrap["suggested_skills"]`; session_start output can include “Suggested Skills: …”. No inputs; no runtime API for arbitrary user text.

### Persona in Skills
- **Mechanism:** Step with `tool: persona_load`, `args: persona_name: "<name>"`; executor calls `server.call_tool("persona_load", args)`.
- **Patterns:** start_work, coffee, beer load developer first; test_mr_ephemeral loads developer → release → devops at different phases. No “restore previous” primitive; restoration = another `persona_load` step.

### Session and Memory
- **Skill completion:** `append_session_entry` with `type: "skill"` in `memory/sessions/YYYY-MM-DD.yaml`.
- **session_close:** Builds entry with `type: "summary"`, accomplished, decisions, next_steps, files_changed; required for coffee/beer.
- **Coffee/beer:** Read session file entries by type (summary, skill, tool, manual); depend on session_close for structured “what was done” and “next steps.”

### Gaps
- **No skill_suggest(user_message) MCP tool** — no API that takes free-form text and returns suggested skill + inputs.
- **No semantic/embedding skill search** — skill_list is full list only.
- **Intent tables are static** — not exposed as JSON or callable API.
- **detect_skill (aa_ollama):** Optional; regex-only; returns skill name only, no inputs.

---

## Agent 4: Skill Testing and Reliability

### Layout
- **tests/skills/:** harness.py, conftest.py, mock_responses.py, fixtures/tool_responses.yaml; test_skill_structural.py, test_skill_templates.py, test_skill_conditions.py, test_skill_regression.py, test_skill_execution.py, test_skill_compute.py.
- **tests/ (root):** test_skill_engine.py (SkillExecutor, ErrorRecoveryMixin, auto_heal), test_skill_error_recovery.py (scripts/common compute error detection), test_auto_heal.py (server auto_heal_decorator), test_auto_heal_common.py.

### Harness
- **SkillTestHarness** wraps real SkillExecutor; replaces `_exec_tool` with async mock that appends (tool_name, args), resolves response from per-test dict → fixtures/tool_responses.yaml → mock_responses.generate_default_response(), writes result into executor.context[tool_name].
- No real I/O; all tools mocked. Helpers: resolve_template, eval_condition, exec_compute, set_context; assertions: assert_tool_called, assert_context_has, assert_all_steps_passed, etc.

### Test Types
| Type | What |
|------|------|
| Structural | Per-skill: YAML, required keys, tool names in registry, compute syntax, outputs, on_error, unique names, inputs. |
| Template | Per-skill: every `{{ }}` in args/outputs/conditions renders; ChainableUndefined, filters. |
| Condition | Unit tests for _eval_condition; smoke over every condition string in every skill. |
| Regression | Anti-patterns: no eval(), no shell=True, no bare except, no forward refs in templates. |
| Execution | Harness-based runs (hello_world, find_similar_code, failures, first 10 non-excluded skills smoke). |
| Compute | _exec_compute_internal, AttrDict, safe_globals, real compute block. |

### Make Targets
- **test-skills:** pytest tests/skills/ (all).
- **test-skills-fast:** structural + template + condition + regression (no execution).
- **test-skills-exec:** execution + compute only.
- **validate-skills:** python scripts/validate_skills.py (structure, tools, links; not pytest).

### Error Recovery Testing
- **test_skill_engine.py:** _find_matched_pattern, _check_error_patterns, _determine_fix_type, _attempt_auto_heal, _handle_tool_error (auto_heal), soft-failure, logging to memory; all with tmp patterns.yaml and mocks.
- **test_auto_heal.py:** server/auto_heal_decorator (retry, auth/network, max retries).
- **Gap:** No dedicated test file for ErrorRecoveryMixin alone; mixin refactors rely on full engine tests.

### Recommendations
1. Run validate-skills in CI.
2. Add output-shape regression for critical skills.
3. Align regression “all skills” with rglob (include subdirs e.g. performance/).
4. Add focused tests for ErrorRecoveryMixin with minimal executor.
5. Add coverage reporting for skill_engine.py and skill_error_recovery.py.
6. Consider exclusions (test_exclusions.yaml) for structural/template tests where needed.

---

## Agent 5: Skill Lifecycle and Ecosystem

### Invocation
- **MCP tool:** `skill_run(skill_name, inputs="{}", args="", execute=True, debug=False)` on server `project-0-redhat-ai-workflow-aa_workflow`.
- **inputs** must be a **JSON string**. Entry: `_skill_run_impl` → load YAML, validate inputs, build SkillExecutor, `await executor.execute()`.

### Categories and Docs
- **docs/skills/README.md:** Categories (Daily Rituals, Development Flow, Code Review, Testing & Deployment, Incident, Jira, Release, Communication, Knowledge, Memory, Project Management, Performance, etc.).
- **docs/commands/:** User-facing slash commands; many map to skills (“Underlying Skill: …” and skill_run examples).
- **skill_list()** at runtime: scans SKILLS_DIR (and performance/); filesystem is the registry.

### Sub-Skills and Chaining
- **Tool step:** `tool: skill_run`, `args: { skill_name, inputs: "<JSON>", execute: true }` → same server, new SkillExecutor in-process.
- **Compute:** `run_skill(skill_name, inputs_dict)` in compute block → same process, sync wrapper.
- **Examples:** jira_update_stale (recursive with different hours_threshold), release_aa_backend_prod (notify_team), test_mr_ephemeral (scan_vulnerabilities, mark_mr_ready, notify_team), coffee/beer (standup_summary, etc.).

### review_pr_multiagent
- **Not 6 MCP tools:** One skill with compute steps that spawn **subprocesses** (Claude/Gemini CLI) and use **threading** for 6 reviewers in parallel; second subprocess for coordinator/synthesis.
- **Flow:** persona_load(developer) → GitLab/knowledge steps → parse_agents → run_all_agents_parallel (single compute: thread pool, subprocess per agent) → synthesize_review (subprocess) → build summary/review/stats → optional gitlab_mr_comment.

### Dependencies and Breakage
- **Tool rename/remove:** Any step with `tool: <name>` fails; validate_skills checks tool names against manifest.
- **Persona rename/remove:** Steps with `persona_load(persona_name: "...")` fail.
- **Skill rename/remove:** `skill_run`/`run_skill` callers fail; link validation checks references.
- **Inputs change:** Callers with wrong/missing inputs get validation errors.
- No static registry of “skill X depends on tools Y”; dependency is implicit in YAML.

---

## Cross-Cutting Summary

| Topic | Agent 1 | Agent 2 | Agent 3 | Agent 4 | Agent 5 |
|-------|---------|---------|---------|---------|---------|
| **Entry** | skill_run → execute() | inputs schema, defaults | skill_list, intent tables | harness, execute() | skill_run signature, lifecycle |
| **Steps** | tool/compute/then/description | Step types, conditions, templating | persona_load steps | Mocked tool steps | skill_run step, run_skill() |
| **Errors** | on_error, auto_heal, retry | on_error values | — | test_skill_engine, test_auto_heal | — |
| **Session** | append_session_entry, session_id | — | session_close, coffee/beer | — | — |
| **Validation** | — | validate_skills.py, links | — | structural tests, validate-skills | Tool/persona/skill refs |

---

## Prioritized Recommendations

1. **Discovery:** Add `skill_suggest(user_message)` MCP tool or embedding-based search; expose intent tables as data/API for “what skill for this phrase?”
2. **Testing:** Include validate-skills in CI; align regression with rglob; add output-shape regression and dedicated ErrorRecoveryMixin tests; report coverage for skill_engine and skill_error_recovery.
3. **Engine:** Document and stabilize tool dispatch and module-loading contract; consider making interactive recovery fully async.
4. **Authoring:** Add “Add a skill” guide (structure, steps, validation, test-skills-fast); optionally maintain a single source of truth for intent tables (e.g. from skill metadata).
5. **Ecosystem:** Document dependency impact (tool/persona/skill renames); consider optional static dependency report (skill → tools/personas/skills) from YAML.

---

*This deep dive was produced by five parallel explore agents. For full agent outputs, re-run the individual agent tasks.*
