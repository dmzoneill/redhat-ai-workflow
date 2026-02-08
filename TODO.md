# Code Quality TODO (Post-Refactoring Audit)

Generated: 2026-02-08 (fresh audit after completing previous 26 TODO items)
Source: 5 parallel code smell audits across 300+ Python files
Total findings: 303 (42 critical, 71 high, 109 medium, 81 low)

---

## Priority 1: Security

- [ ] **SEC-001**: Remove `subprocess` from compute sandbox allowed imports (`skill_compute_engine.py:59` `_ALLOWED_COMPUTE_MODULES`). Undermines the security hardening that removed `open`/`__import__`.
- [ ] **SEC-002**: `scripts/common/video_device.py:192` — `subprocess.run(..., shell=True)` with glob pattern `/dev/video*`. Replace with `shell=False` and explicit glob expansion.
- [ ] **SEC-003**: `scripts/get_slides_info.py:12` — Hardcoded Google presentation ID. Move to config or CLI argument.

## Priority 2: God Files Needing Decomposition

- [ ] **GOD-001**: `server/workspace_state.py` (2860 lines) — Split into `cursor_db.py`, `chat_session.py`, `workspace_registry.py`. Has 6 functions over 130 lines and `noqa: C901` suppression.
- [ ] **GOD-002**: `server/utils.py` (1107 lines) — Split into `formatting.py`, `kubeconfig.py`, `command_runner.py`. Three `run_cmd` variants share 80% identical code.
- [ ] **GOD-003**: `services/slack/daemon.py` — `CommandHandler` inner class is 1230 lines with 20+ `_handle_*` methods. Extract command handlers into separate modules.
- [ ] **GOD-004**: `services/slack/dbus.py` (2758 lines) — Still massive. Extract formatting/history from D-Bus protocol.
- [ ] **GOD-005**: `tool_modules/aa_meet_bot/src/browser_controller.py` — `GoogleMeetController` 3833 lines. Extract sign-in, meeting joining, participant management into focused classes.
- [ ] **GOD-006**: `tool_modules/aa_meet_bot/src/video_generator.py` — `RealtimeVideoRenderer` 2014 lines.
- [ ] **GOD-007**: `tool_modules/aa_slack/src/slack_client.py` — `SlackSession` 2466 lines.
- [ ] **GOD-008**: 12 `register_tools()` god functions (300-744 lines each) across tool modules. Systemic pattern: `aa_code_search` (744), `aa_github` (719), `aa_performance` (701), `aa_libvirt` (641), `aa_concur` (595), `aa_meet_bot` (499), `aa_ansible` (496), `aa_scheduler` (495), `aa_docker` (475), `aa_slack` (372), etc.

## Priority 3: Remaining Duplicate Code

- [ ] **DUP-001**: `AttrDict` defined identically in `skill_engine.py:43-62` and `skill_compute_engine.py:84-103`. Define once, import.
- [ ] **DUP-002**: `ACTIONABLE_STATUSES` + `is_actionable()` duplicated in 3 files: `sprint_bot.py:525-536`, `sprint_history.py:457-468`, `sprint_tools.py:45-55`.
- [ ] **DUP-003**: Auth/network pattern lists duplicated between `skill_auto_healer.py` methods (`determine_fix_type:113-118` vs `detect_auto_heal_type:140-164`) and `scheduler.py:769-822`.
- [ ] **DUP-004**: `_detect_project_from_cwd()` duplicated in `session_tools.py:514` and `chat_context.py:183`.
- [ ] **DUP-005**: `_get_current_persona()` duplicated in `session_tools.py:538` and `knowledge_tools.py:261`.
- [ ] **DUP-006**: Slack conversation-fetching pattern duplicated in 3 files: `common/slack_export.py` (canonical), `run_slack_export.py`, `slack_export_test.py`.
- [ ] **DUP-007**: `cluster_map` duplicated in `utils.py:850-861`, `auto_heal_decorator.py:93-100`, and within `utils.py:203-222` (`KUBECONFIG_MAP`).
- [ ] **DUP-008**: Atomic `_write_state()` pattern (tempfile + rename) copied in 4 daemons (sprint, session, meet, cron). Extract to `BaseDaemon`.
- [ ] **DUP-009**: `_handle_approve/reject/abort/skip_issue` in sprint daemon follow identical validate→load→find→update→save pattern.

## Priority 4: Hardcoded Paths & Values

- [ ] **HARD-001**: `scripts/common/memory.py:38` — `MEMORY_DIR = Path.home() / "src/redhat-ai-workflow/memory"`. User-specific.
- [ ] **HARD-002**: `skill_auto_healer.py:488,550` — Hardcoded OpenShift cluster URLs. Move to config.
- [ ] **HARD-003**: `skill_auto_healer.py:488` — VPN script path `~/src/redhatter/...`. Still hardcoded.
- [ ] **HARD-004**: `services/sprint/daemon.py:583-604` — `Path.home() / "src" / "redhat-ai-workflow" / "memory"` hardcoded.
- [ ] **HARD-005**: `infra_tools.py:32-34` — `/tmp/aa_workflow_vpn.lock` etc. Collide in multi-user envs.
- [ ] **HARD-006**: `config_loader.py` — Hardcoded defaults: `issues.redhat.com`, `Europe/Dublin`, `gitlab.cee.redhat.com`, `aap-aa-tenant`.
- [ ] **HARD-007**: `server/config.py:173` — Fallback UID `1000`. Use `os.getuid()`.

## Priority 5: Silent Exception Swallowing (remaining)

- [ ] **ERR-001**: `aa_sso/tools_basic.py` — 11 bare `except Exception:` blocks (worst single file).
- [ ] **ERR-002**: `scripts/mcp_proxy.py` — 3 bare `except Exception:` in critical proxy code.
- [ ] **ERR-003**: `scripts/claude_agent.py` — 3 bare `except Exception:` blocks.
- [ ] **ERR-004**: `aa_meet_bot/video_generator.py` — 2 bare `except Exception:` in rendering.
- [ ] **ERR-005**: `aa_google_slides/tools_basic.py` — 3 bare `except Exception:` in service init.
- [ ] **ERR-006**: `server/workspace_state.py` — 5 remaining silent exception blocks.
- [ ] **ERR-007**: `server/main.py` — `load_agent_config()` silently returns None on all errors.

## Priority 6: Race Conditions & Global State

- [ ] **RACE-001**: `services/slack/dbus.py:215-219` — `ApproveMessage` blocks D-Bus thread with `future.result(timeout=30)`. Can deadlock.
- [ ] **RACE-002**: `services/slack/dbus.py:257-281` — `SendMessage` fire-and-forgets async coroutine without tracking result.
- [ ] **RACE-003**: `services/memory_abstraction/interface.py:454-481` — `set_memory_interface()` has no lock despite `get` having one.
- [ ] **RACE-004**: `tools_basic.py:55` — `_recent_issues` module-level dict modified without thread safety.

## Priority 7: Test Quality

- [ ] **TEST-001**: 12 test files exceed 1000 lines. Largest: `test_skill_engine.py` (5529), `test_workspace_state.py` (4258), `test_session_tools.py` (2888).
- [ ] **TEST-002**: 653 `MagicMock()` calls without `spec=` across 37 files. Allows accessing any attribute — typos pass silently.
- [ ] **TEST-003**: 3 non-test files still in tests/: `test_slack_export_full.py` (real network calls), `integration_test.py`, `skill_test_runner.py`.
- [ ] **TEST-004**: Singleton `_instance = None` manipulation appears 46 times across 6 files without fixture cleanup.
- [ ] **TEST-005**: Deprecated `event_loop` fixture in `test_meetbot_devices.py:967`. Manual `asyncio.new_event_loop()` in 3 files.
- [ ] **TEST-006**: `test_jira_utils.py:59-65` — Test catches TypeError/AttributeError with pass. Validates nothing.
- [ ] **TEST-007**: `skills/test_skill_execution.py:21-108` — Duplicate `SkillHarness` class and `test_exclusions` fixture (already in conftest).

## Priority 8: Deep Nesting (>4 levels)

- [ ] **NEST-001**: `scripts/analyze_chat_commands.py:157,221` — 13 levels deep.
- [ ] **NEST-002**: `scripts/mcp_proxy.py:436` — 11 levels deep.
- [ ] **NEST-003**: `tool_modules/aa_slack/src/tools_style.py:71,86` — 11 levels deep.
- [ ] **NEST-004**: `services/sprint/issue_executor.py:689-993` — `_run_issue_in_background_traced()` 305 lines, 5+ levels.
- [ ] **NEST-005**: `services/session/daemon.py:198-331` — `_handle_search_chats()` 6 levels.

## Priority 9: TODO/FIXME Comments

- [ ] `scripts/context_injector.py:780` — TODO: async parallelism
- [ ] `scripts/common/skill_error_recovery.py:460` — TODO: ruamel.yaml formatting
- [ ] `tool_modules/aa_performance/src/tools_basic.py:140` — TODO: actual data fetchers
- [ ] `tool_modules/aa_meet_bot/src/intel_streaming.py:691` — TODO: VA-API JPEG encoder
- [ ] `tool_modules/aa_meet_bot/src/tools_basic.py:537,542` — TODO: audio playback
- [ ] `server/main.py:80` — TODO: FastMCP sync API migration
- [ ] `server/debuggable.py:401` — TODO: FastMCP tool handler API migration

## Priority 10: Minor Cleanup

- [ ] Operator precedence bug: `server/debuggable.py:228-234` — `or`/`and` chain needs parentheses.
- [ ] `infra_tools.py:122-136` — f-string bug: `{vpn_script}` inside regular string, not f-string.
- [ ] `project_tools.py:91-92` — Typo: `git symbolic-re` should be `git symbolic-ref`.
- [ ] `knowledge_tools.py:207` — `_emit_knowledge_notification()` defined but never called.
- [ ] `sprint_history.py:59` — `MAX_TIMELINE_ENTRIES` as instance field on dataclass. Use `ClassVar`.
- [ ] `skill_compute_engine.py:24-25` — Empty `if TYPE_CHECKING: pass` block.
- [ ] Replace `Optional[X]` with `X | None` in 8 server files for consistency.
- [ ] Remove deprecated aliases: `config.py:199` `get_docker_auth`, `__init__.py:6` `load_repos_config`, `workspace_utils.py:241` `is_tool_active_for_workspace`.
- [ ] Remove deprecated paths: `paths.py:75` `SPRINT_STATE_FILE`, `paths.py:84` `UNIFIED_WORKSPACE_STATES_FILE`.
