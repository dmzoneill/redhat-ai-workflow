# Code Quality TODO (Round 3 Audit)

Generated: 2026-02-08
Source: 2 parallel audits across server/, scripts/, tool_modules/, services/
Previous rounds: 26 items completed (round 1), 18 items completed (round 2)

---

## Priority 1: Bugs

- [ ] **BUG-001**: `server/websocket_server.py:649` — `except asyncio.TimeoutExpired` should be `except asyncio.TimeoutError`. `asyncio.TimeoutExpired` doesn't exist — this catches `subprocess.TimeoutExpired` instead, so the Zenity confirmation timeout fallback is silently broken.

## Priority 2: Massive Code Duplication (87+ functions)

- [ ] **DUP-001**: `aa_knowledge/tools_basic.py` vs `aa_workflow/knowledge_tools.py` — **15 functions fully duplicated**. Merge to single source.
- [ ] **DUP-002**: `aa_project/tools_basic.py` vs `aa_workflow/project_tools.py` — **17 functions fully duplicated**. Merge to single source.
- [ ] **DUP-003**: `aa_scheduler/tools_basic.py` vs `aa_workflow/scheduler_tools.py` — **9 functions fully duplicated**. Merge to single source.
- [ ] **DUP-004**: `aa_docker/tools_basic.py` vs `aa_git/tools_basic.py` — **8 Docker functions** verbatim copies.
- [ ] **DUP-005**: `_basic.py` vs `_extra.py` duplication across 7 modules — quay (7 funcs), kibana (6), alertmanager (2), gitlab (4), bonfire (4), konflux (3), lint (1). Extract shared helpers to each module's common file.
- [ ] **DUP-006**: `_load_config()` duplicated in 8 files, `_get_slack_config()` in 4 files, `_get_google_config_dir()` in 3 files, Google OAuth helpers in 2 files. Extract to `tool_modules/common/`.
- [ ] **DUP-007**: Daemon boilerplate (`get_service_status`, `_handle_get_state`, `shutdown`, `run_daemon`) duplicated across 7-13 daemon files. Move to `BaseDaemon` defaults.
- [ ] **DUP-008**: `workspace_state.py` — `get_cursor_chat_personas()` and `get_cursor_chat_projects()` share identical DB scanning boilerplate. Extract `_scan_cursor_chats()`.
- [ ] **DUP-009**: Cursor DB path `~/.config/Cursor/User/...` hardcoded in 7+ locations in workspace_state.py. Extract to `server/paths.py`.

## Priority 3: God Classes (35 classes over 500 lines)

Top 10 by size:
- [ ] `GoogleMeetController` — 3,833 lines (browser_controller.py)
- [ ] `SlackSession` — 2,466 lines (slack_client.py)
- [ ] `RealtimeVideoRenderer` — 2,350 lines (video_generator.py)
- [ ] `SlackPersonaDBusInterface` — 2,106 lines (services/slack/dbus.py)
- [ ] `SkillExecutor` — 1,661 lines (still large after decomposition)
- [ ] `NotesBot` — 1,586 lines (notes_bot.py)
- [ ] `CommandHandler` — 1,229 lines (services/slack/daemon.py)
- [ ] `SlackStateDB` — 1,197 lines (persistence.py)
- [ ] `SprintDaemon` — 1,147 lines (still large after decomposition)
- [ ] `IssueExecutor` — 1,045 lines (issue_executor.py)

## Priority 4: God Functions (149 functions over 100 lines)

Top offenders:
- [ ] `register_meta_tools()` — 974 lines (meta_tools.py)
- [ ] `register_tools()` — 744 lines (aa_code_search)
- [ ] `register_tools()` — 719 lines (aa_github)
- [ ] `_register_builtin_tools()` — 547 lines (claude_agent.py)
- [ ] `sync_with_cursor_db()` — 297 lines (workspace_state.py)
- [ ] `run_export()` — 237 lines (run_slack_export.py)
- [ ] `load_from_disk()` — 182 lines (workspace_state.py)
- [ ] `get_cursor_chat_content()` — 181 lines (workspace_state.py)
- [ ] `classify_error_type()` — 179 lines (usage_pattern_classifier.py)
- [ ] `inject_context_to_cursor_chat()` — 171 lines (workspace_state.py)

## Priority 5: Silent Excepts (170+ remaining)

- [ ] `aa_meet_bot/browser_controller.py` — 16 instances
- [ ] `aa_meet_bot/notes_bot.py` — 12 instances
- [ ] `aa_workflow/infra_tools.py` — 8 instances
- [ ] `aa_workflow/knowledge_tools.py` — 3 instances
- [ ] `aa_workflow/project_tools.py` — 5 instances
- [ ] `services/base/daemon.py` — 2 instances
- [ ] 37 additional files — 105 more instances
- [ ] Total: ~170 `except ...: pass` blocks that should at minimum log

## Priority 6: Race Conditions & Thread Safety

- [ ] `server/workspace_state.py` — `_workspaces` dict and `_access_count` on WorkspaceRegistry with no lock
- [ ] `server/workspace_state.py:92` — `_persona_tool_counts` module-level dict, no lock
- [ ] `server/debuggable.py:42` — `TOOL_REGISTRY` module-level dict, no lock
- [ ] `server/tool_discovery.py:119` — `TOOL_MANIFEST` singleton, no lock
- [ ] `server/persona_loader.py:112` — `_discovered_modules` TOCTOU race
- [ ] `aa_sso/tools_basic.py:1055` — 4 browser globals modified in async without lock
- [ ] `aa_meet_bot/tools_basic.py:65-718` — 6 globals modified in async without lock
- [ ] `aa_meet_bot/browser_controller.py:153` — `_instance_counter` incremented without lock

## Priority 7: Remaining Hardcoded Values

- [ ] `aa_meet_bot/tts_engine.py:32,329` — `/home/daoneill/src/GPT-SoVITS`
- [ ] `aa_meet_bot/config.py:104` — `/home/daoneill/Documents/Identification/IMG_3249_.jpg`
- [ ] `server/websocket_server.py:588-604` — Linux sound file paths
- [ ] `server/workspace_state.py` — Cursor DB path in 7+ locations

## Priority 8: Deep Nesting (173 functions > 4 levels)

Top offenders:
- [ ] `CommandHandler.handle` — 16 levels (services/slack/daemon.py)
- [ ] `register_tools` / `slack_export_my_messages` — 11 levels (aa_slack/tools_style.py)
- [ ] `_google_calendar_quick_meeting_impl` — 10 levels
- [ ] `sign_in_google` — 10 levels (browser_controller.py)

## Priority 9: Dead Code & Deprecated

- [ ] `workspace_state.py:2147` — `sync_session_names_from_cursor()` deprecated but present
- [ ] `workspace_utils.py:241` — `is_tool_active_for_workspace()` always returns True
- [ ] `workspace_state.py:1463` — `ChatSession.active_tools` deprecated property
- [ ] `video_generator.py:67-73` — `try: pass` with unreachable except
- [ ] `scripts/archived/` — entire directory of old migration scripts
- [ ] `session_builder.py:455` and `ralph_loop_manager.py:307` — `if __name__ == "__main__"` CLI test blocks in library modules

## Priority 10: Import Side Effects

- [ ] 6 server modules load `config.json` at import time via `load_config()`
- [ ] `video_generator.py:26` and `gpu_text.py:18` — `os.environ.setdefault()` at import
- [ ] `workspace_state.py:87` — late import after code execution (has noqa)
