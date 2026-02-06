# =============================================================================
# AI Workflow Makefile
# =============================================================================
# Targets for running MCP servers, the Slack daemon, and development tasks.
#
# Usage:
#   make help              - Show available targets
#   make slack-daemon      - Run Slack daemon (foreground)
#   make slack-daemon-bg   - Run Slack daemon (background)
#   make mcp-server        - Run MCP server (developer agent)
#   make test              - Run tests
# =============================================================================

.PHONY: help install install-dev test lint format clean \
        check-env config-validate status quick-start \
        slack-daemon slack-daemon-bg slack-daemon-stop slack-daemon-logs \
        slack-daemon-verbose slack-daemon-dry slack-daemon-debug slack-daemon-dbus slack-daemon-status \
        slack-test slack-status slack-pending slack-approve slack-approve-all \
        slack-reject slack-history slack-send slack-watch slack-reload \
        mcp-server mcp-developer mcp-devops mcp-incident mcp-release mcp-slack mcp-all mcp-custom \
        integration-test integration-test-agent integration-test-fix integration-test-dry \
        skill-test skill-test-list skill-test-dry \
        docs-serve docs-check list-skills list-tools list-modules \
        validate-personas generate-personas generate-personas-dry \
        sync-ai-rules sync-ai-rules-dry sync-ai-rules-verbose \
        sync-commands sync-commands-dry sync-commands-reverse \
        sync-config-example sync-config-example-fix \
        ext-build ext-install ext-watch ext-clean ext-package \
        super-lint

# Use bash for proper escape sequence handling
SHELL := /bin/bash

# Configuration
PYTHON := python3
UV := uv
PROJECT_ROOT := $(shell pwd)
VENV := $(PROJECT_ROOT)/.venv
SLACK_LOG := /tmp/slack-daemon.log
SLACK_PID := /tmp/slack-daemon.pid

# Default target
.DEFAULT_GOAL := help

# =============================================================================
# HELP
# =============================================================================

help:
	@printf "\n"
	@printf "\033[36m\033[1m╔══════════════════════════════════════════════════════════════════╗\033[0m\n"
	@printf "\033[36m\033[1m║  AI Workflow - Development & Runtime Commands                    ║\033[0m\n"
	@printf "\033[36m\033[1m╚══════════════════════════════════════════════════════════════════╝\033[0m\n"
	@printf "\n"
	@printf "\033[1mSlack Daemon:\033[0m\n"
	@printf "  \033[32mmake slack-daemon\033[0m       Run Slack daemon (foreground, Ctrl+C to stop)\n"
	@printf "  \033[32mmake slack-daemon-bg\033[0m    Run Slack daemon (background with D-Bus)\n"
	@printf "  \033[32mmake slack-daemon-stop\033[0m  Stop background Slack daemon\n"
	@printf "  \033[32mmake slack-daemon-logs\033[0m  Tail Slack daemon logs\n"
	@printf "  \033[32mmake slack-daemon-verbose\033[0m  Run with verbose logging\n"
	@printf "  \033[32mmake slack-daemon-dry\033[0m   Run in dry-run mode (no responses sent)\n"
	@printf "  \033[32mmake slack-daemon-debug\033[0m Run in DEBUG mode (responses go to self-DM)\n"
	@printf "  \033[32mmake slack-test\033[0m         Quick smoke test (validates credentials)\n"
	@printf "\n"
	@printf "\033[1mSlack Control (D-Bus IPC):\033[0m\n"
	@printf "  \033[32mmake slack-status\033[0m       Get daemon status and stats\n"
	@printf "  \033[32mmake slack-pending\033[0m      List messages awaiting approval\n"
	@printf "  \033[32mmake slack-approve ID=xxx\033[0m  Approve a specific message\n"
	@printf "  \033[32mmake slack-approve-all\033[0m  Approve all pending messages\n"
	@printf "  \033[32mmake slack-reject ID=xxx\033[0m  Reject a specific message\n"
	@printf "  \033[32mmake slack-history\033[0m      Show message history\n"
	@printf "  \033[32mmake slack-watch\033[0m        Watch for new messages (live)\n"
	@printf "  \033[32mmake slack-reload\033[0m       Reload daemon configuration\n"
	@printf "  \033[32mmake slack-send\033[0m         Send message (TARGET=C.../U.../@user MSG=...)\n"
	@printf "\n"
	@printf "\033[1mMCP Servers:\033[0m\n"
	@printf "  \033[32mmake mcp-server\033[0m         Run MCP server (default: developer)\n"
	@printf "  \033[32mmake mcp-developer\033[0m      Run developer agent\n"
	@printf "  \033[32mmake mcp-devops\033[0m         Run devops agent\n"
	@printf "  \033[32mmake mcp-incident\033[0m       Run incident agent\n"
	@printf "  \033[32mmake mcp-release\033[0m        Run release agent\n"
	@printf "  \033[32mmake mcp-slack\033[0m          Run slack agent\n"
	@printf "  \033[32mmake mcp-all\033[0m            Run with ALL tools (may exceed limits)\n"
	@printf "  \033[32mmake mcp-custom TOOLS=x,y\033[0m  Run with specific tool modules\n"
	@printf "\n"
	@printf "\033[1mDevelopment:\033[0m\n"
	@printf "  \033[32mmake install\033[0m            Install dependencies\n"
	@printf "  \033[32mmake install-dev\033[0m        Install dev dependencies (pytest, black, etc)\n"
	@printf "  \033[32mmake test\033[0m               Run unit tests\n"
	@printf "  \033[32mmake lint\033[0m               Run linters (flake8, black --check)\n"
	@printf "  \033[32mmake super-lint\033[0m         Run GitHub Super-Linter (via Docker)\n"
	@printf "  \033[32mmake format\033[0m             Auto-format code with black\n"
	@printf "  \033[32mmake check-env\033[0m          Validate Slack configuration\n"
	@printf "\n"
	@printf "\033[1mTesting:\033[0m\n"
	@printf "  \033[32mmake integration-test\033[0m   Run integration tests across agents\n"
	@printf "  \033[32mmake integration-test-fix\033[0m  Run with auto-fix enabled\n"
	@printf "  \033[32mmake skill-test\033[0m         Run skill tests (live execution)\n"
	@printf "  \033[32mmake skill-test-list\033[0m    List all skills\n"
	@printf "  \033[32mmake skill-test-dry\033[0m     Run skill tests (dry-run)\n"
	@printf "\n"
	@printf "\033[1mDocumentation:\033[0m\n"
	@printf "  \033[32mmake list-skills\033[0m        List all available skills\n"
	@printf "  \033[32mmake list-tools\033[0m         List all MCP tool modules\n"
	@printf "  \033[32mmake list-modules\033[0m       List modules and skills (detailed)\n"
	@printf "  \033[32mmake docs-serve\033[0m         Serve docs locally (port 8000)\n"
	@printf "  \033[32mmake docs-check\033[0m         Check for missing skill docs\n"
	@printf "\n"
	@printf "\033[1mPersona Management:\033[0m\n"
	@printf "  \033[32mmake validate-personas\033[0m  Validate persona YAML files\n"
	@printf "  \033[32mmake generate-personas\033[0m  Regenerate all persona YAML files\n"
	@printf "  \033[32mmake generate-personas-dry\033[0m  Preview persona changes\n"
	@printf "\n"
	@printf "\033[1mProject Tools (ptools):\033[0m\n"
	@printf "  \033[32mmake sync-ai-rules\033[0m      Sync AI rules to .cursorrules, CLAUDE.md, AGENTS.md + commands\n"
	@printf "  \033[32mmake sync-ai-rules-dry\033[0m  Preview AI rules sync without making changes\n"
	@printf "  \033[32mmake sync-commands\033[0m      Generate missing + sync Cursor commands to Claude Code\n"
	@printf "  \033[32mmake sync-commands-dry\033[0m  Preview sync without making changes\n"
	@printf "  \033[32mmake sync-commands-reverse\033[0m  Sync Claude Code to Cursor format\n"
	@printf "  \033[32mmake sync-commands-generate\033[0m  Generate Cursor commands for new skills\n"
	@printf "  \033[32mmake sync-config-example\033[0m  Check config.json.example has all keys\n"
	@printf "  \033[32mmake sync-config-example-fix\033[0m  Add missing keys to example\n"
	@printf "\n"
	@printf "\033[1mVSCode Extension:\033[0m\n"
	@printf "  \033[32mmake ext-build\033[0m          Build the VSCode/Cursor extension\n"
	@printf "  \033[32mmake ext-install\033[0m        Install extension to Cursor (symlink)\n"
	@printf "  \033[32mmake ext-watch\033[0m          Watch and rebuild on changes\n"
	@printf "  \033[32mmake ext-clean\033[0m          Clean extension build artifacts\n"
	@printf "  \033[32mmake ext-package\033[0m        Package as .vsix for distribution\n"
	@printf "\n"
	@printf "\033[1mUtilities:\033[0m\n"
	@printf "  \033[32mmake config-validate\033[0m    Validate config.json\n"
	@printf "  \033[32mmake clean\033[0m              Clean temporary files\n"
	@printf "  \033[32mmake status\033[0m             Show status of running processes\n"
	@printf "  \033[32mmake quick-start\033[0m        Show quick start guide\n"
	@printf "\n"

# =============================================================================
# INSTALLATION
# =============================================================================

install:
	@printf "\033[36mInstalling dependencies...\033[0m\n"
	$(UV) sync
	@printf "\033[32m✅ Dependencies installed\033[0m\n"

install-dev: install
	@printf "\033[36mInstalling dev dependencies...\033[0m\n"
	$(UV) sync --extra dev
	@printf "\033[32m✅ Dev dependencies installed\033[0m\n"

# =============================================================================
# SLACK DAEMON
# =============================================================================

# Check config.json for Slack credentials (environment vars are optional overrides)
check-env:
	@printf "\033[36mChecking Slack configuration...\033[0m\n"
	@if [ ! -f "$(PROJECT_ROOT)/config.json" ]; then \
		printf "\033[31m❌ config.json not found\033[0m\n"; \
		echo "   Copy config.example.json to config.json and fill in your credentials"; \
		exit 1; \
	fi
	@$(PYTHON) -c "import json; c=json.load(open('config.json')); \
		t=c.get('slack',{}).get('auth',{}).get('xoxc_token',''); \
		exit(0 if t else 1)" 2>/dev/null && \
		printf "\033[32m✅ Slack credentials found in config.json\033[0m\n" || \
		(printf "\033[31m❌ slack.auth.xoxc_token not set in config.json\033[0m\n" && exit 1)
	@printf "\n"

# Quick smoke test - validates credentials and sends a test DM to yourself
slack-test:
	@printf "\033[36mRunning Slack smoke test...\033[0m\n\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_test.py

slack-daemon: check-env
	@printf "\033[36mStarting Slack daemon (foreground)...\033[0m\n"
	@printf "\033[33mPress Ctrl+C to stop\033[0m\n\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py

slack-daemon-verbose: check-env
	@printf "\033[36mStarting Slack daemon (verbose)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --verbose

slack-daemon-dry: check-env
	@printf "\033[36mStarting Slack daemon (dry-run mode)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --dry-run --verbose

slack-daemon-debug: check-env
	@printf "\033[36mStarting Slack daemon (DEBUG MODE)...\033[0m\n"
	@printf "\033[33m🐛 All responses will be sent to your self-DM instead of original recipients\033[0m\n\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --debug --verbose

slack-daemon-stop:
	@# Try to kill by PID file first
	@if [ -f $(SLACK_PID) ]; then \
		PID=$$(cat $(SLACK_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo $$'\033[36m'"Stopping daemon (PID: $$PID)..."$$'\033[0m'; \
			kill $$PID; \
			echo $$'\033[32m✅ Daemon stopped\033[0m'; \
		else \
			echo $$'\033[33m⚠️  Process not running\033[0m'; \
		fi; \
	else \
		pkill -f slack_daemon.py 2>/dev/null && \
			echo $$'\033[32m✅ Daemon stopped (by process name)\033[0m' || \
			echo $$'\033[33m⚠️  No daemon running\033[0m'; \
	fi
	@# Always clean up lock/pid files
	@rm -f $(SLACK_PID) /tmp/slack-daemon.lock 2>/dev/null || true

slack-daemon-logs:
	@if [ -f $(SLACK_LOG) ]; then \
		echo -e "\033[36mTailing $(SLACK_LOG)...\033[0m"; \
		tail -f $(SLACK_LOG); \
	else \
		echo -e "\033[33m⚠️  No log file found\033[0m"; \
	fi

slack-daemon-status:
	@if [ -f $(SLACK_PID) ] && kill -0 $$(cat $(SLACK_PID)) 2>/dev/null; then \
		echo -e "\033[32m✅ Daemon running (PID: $$(cat $(SLACK_PID)))\033[0m"; \
	else \
		echo -e "\033[33m⚠️  Daemon not running\033[0m"; \
	fi

# D-Bus daemon with IPC enabled
slack-daemon-dbus: check-env
	@printf "\033[36mStarting Slack daemon with D-Bus IPC...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --dbus

slack-daemon-bg: check-env
	@printf "\033[36mStarting Slack daemon (background with D-Bus)...\033[0m\n"
	@if [ -f $(SLACK_PID) ] && kill -0 $$(cat $(SLACK_PID)) 2>/dev/null; then \
		echo -e "\033[33m⚠️  Daemon already running (PID: $$(cat $(SLACK_PID)))\033[0m"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && \
		nohup $(PYTHON) scripts/slack_daemon.py --dbus > $(SLACK_LOG) 2>&1 & \
		echo $$! > $(SLACK_PID)
	@sleep 2
	@printf "\033[32m✅ Daemon started (PID: $$(cat $(SLACK_PID)))\033[0m\n"
	@echo "   D-Bus: com.aiworkflow.BotSlack"
	@echo "   Logs: $(SLACK_LOG)"
	@echo "   Stop: make slack-daemon-stop"

# =============================================================================
# SLACK CONTROL (D-Bus IPC)
# =============================================================================

slack-status:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py status

slack-pending:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py pending -v

slack-approve:
	@if [ -z "$(ID)" ]; then \
		echo -e "\033[31m❌ Usage: make slack-approve ID=<message_id>\033[0m"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py approve $(ID)

slack-approve-all:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py approve-all

slack-reject:
	@if [ -z "$(ID)" ]; then \
		echo -e "\033[31m❌ Usage: make slack-reject ID=<message_id>\033[0m"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py reject $(ID)

slack-history:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py history -n 50 -v

slack-watch:
	@printf "\033[36mWatching for new messages (Ctrl+C to stop)...\033[0m\n"
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py watch

slack-reload:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py reload

slack-send:
	@TARGET_VAL=$${TARGET:-$$CHANNEL}; \
	if [ -z "$$TARGET_VAL" ] || [ -z "$(MSG)" ]; then \
		echo -e "\033[31m❌ Usage:\033[0m"; \
		echo "  make slack-send TARGET=C12345678 MSG='Hello!'  # Channel"; \
		echo "  make slack-send TARGET=U12345678 MSG='Hello!'  # User (DM)"; \
		echo "  make slack-send TARGET=@username MSG='Hello!'  # User by name"; \
		exit 1; \
	fi; \
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py send "$$TARGET_VAL" "$(MSG)"

# =============================================================================
# MCP SERVERS
# =============================================================================

mcp-server: mcp-developer

mcp-developer:
	@printf "\033[36mStarting MCP server (developer agent)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --agent developer

mcp-devops:
	@printf "\033[36mStarting MCP server (devops agent)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --agent devops

mcp-incident:
	@printf "\033[36mStarting MCP server (incident agent)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --agent incident

mcp-release:
	@printf "\033[36mStarting MCP server (release agent)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --agent release

mcp-slack:
	@printf "\033[36mStarting MCP server (slack agent)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --agent slack

mcp-all:
	@printf "\033[33m⚠️  Loading ALL tools - may exceed Cursor's 128 tool limit!\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --all

mcp-custom:
	@printf "\033[36mUsage: make mcp-custom TOOLS='git,jira,slack'\033[0m\n"
	@if [ -z "$(TOOLS)" ]; then \
		echo -e "\033[31m❌ TOOLS not specified\033[0m"; \
		exit 1; \
	fi
	cd $(PROJECT_ROOT) && $(PYTHON) -m server --tools $(TOOLS)

# =============================================================================
# DEVELOPMENT
# =============================================================================

test:
	@printf "\033[36mRunning tests...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) -m pytest tests/ -v

# Integration tests with auto-remediation
integration-test:
	@printf "\033[36mRunning integration tests across all agents...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/integration_test.py --save

integration-test-agent:
	@printf "\033[36mRunning integration tests for agent: $(AGENT)\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/integration_test.py --agent $(AGENT)

integration-test-fix:
	@printf "\033[36mRunning integration tests with auto-fix...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/integration_test.py --fix --save

integration-test-dry:
	@printf "\033[36mRunning integration tests (dry-run)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/integration_test.py --dry-run

# Skill tests - actually execute skills with safe params
skill-test:
	@printf "\033[36mRunning skill tests (live execution)...\033[0m\n"
	cd $(PROJECT_ROOT) && source ~/bonfire_venv/bin/activate && $(PYTHON) scripts/skill_test_runner.py

skill-test-list:
	@printf "\033[36mListing all skills...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/skill_test_runner.py --list

skill-test-dry:
	@printf "\033[36mRunning skill tests (dry-run)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/skill_test_runner.py --dry-run

lint:
	@printf "\033[36mRunning linters...\033[0m\n"
	cd $(PROJECT_ROOT) && flake8 scripts/ tool_modules/ --max-line-length=120 --ignore=E501,W503,E402,C901,E203,E226,E228,F841
	cd $(PROJECT_ROOT) && black --check scripts/ tool_modules/ --line-length=120
	@printf "\033[32m✅ Linting passed\033[0m\n"

super-lint:
	@printf "\033[36mRunning Super-Linter (via Docker)...\033[0m\n"
	$(PROJECT_ROOT)/scripts/run-super-linter.sh
	@printf "\033[32m✅ Super-Linter passed\033[0m\n"

format:
	@printf "\033[36mFormatting code...\033[0m\n"
	cd $(PROJECT_ROOT) && black scripts/ tool_modules/ --line-length=120
	@printf "\033[32m✅ Code formatted\033[0m\n"

# =============================================================================
# DOCUMENTATION
# =============================================================================

docs-serve:
	@printf "\033[36mServing documentation...\033[0m\n"
	@printf "Open http://localhost:8000 in your browser\n"
	cd $(PROJECT_ROOT)/docs && $(PYTHON) -m http.server 8000

docs-check:
	@printf "\033[36mChecking documentation...\033[0m\n"
	@echo "Skills with docs:"
	@ls -1 $(PROJECT_ROOT)/docs/skills/*.md 2>/dev/null | wc -l
	@echo "Skills without docs:"
	@for skill in $(PROJECT_ROOT)/skills/*.yaml; do \
		name=$$(basename $$skill .yaml); \
		if [ ! -f "$(PROJECT_ROOT)/docs/skills/$$name.md" ]; then \
			echo "  ❌ $$name"; \
		fi; \
	done

list-skills:
	@printf "\033[36mAvailable Skills:\033[0m\n"
	@for skill in $(PROJECT_ROOT)/skills/*.yaml; do \
		name=$$(basename $$skill .yaml); \
		desc=$$(grep -m1 "^description:" $$skill 2>/dev/null | sed 's/description: *//; s/"//g' | head -c 60); \
		printf "  \033[32m%-25s\033[0m %s\n" "$$name" "$$desc"; \
	done

list-tools:
	@printf "\033[36mMCP Tool Modules:\033[0m\n"
	@for dir in $(PROJECT_ROOT)/tool_modules/aa-*/; do \
		name=$$(basename $$dir); \
		if [ -f "$$dir/src/tools.py" ]; then \
			count=$$(grep -c "@server.tool" $$dir/src/tools.py 2>/dev/null || echo "0"); \
			printf "  \033[32m%-20s\033[0m %s tools\n" "$$name" "$$count"; \
		fi; \
	done

# =============================================================================
# PERSONA MANAGEMENT
# =============================================================================

validate-personas:
	@printf "\033[36mValidating persona YAML files...\033[0m\n"
	$(PYTHON) scripts/generate_persona_yaml.py --validate

generate-personas:
	@printf "\033[36mRegenerating persona YAML files...\033[0m\n"
	$(PYTHON) scripts/generate_persona_yaml.py --regenerate-all

generate-personas-dry:
	@printf "\033[36mPreviewing persona changes (dry-run)...\033[0m\n"
	$(PYTHON) scripts/generate_persona_yaml.py --regenerate-all --dry-run

list-modules:
	@printf "\033[36mListing available tool modules and skills...\033[0m\n"
	$(PYTHON) scripts/generate_persona_yaml.py --list

config-validate:
	@printf "\033[36mValidating config.json...\033[0m\n"
	@$(PYTHON) -c "import json; json.load(open('config.json')); print('\033[32m✅ Valid JSON\033[0m')"
	@$(PYTHON) -c "import json; c=json.load(open('config.json')); \
		r=c.get('repositories',{}); \
		u=c.get('user',{}); \
		s=c.get('slack',{}).get('auth',{}); \
		print(f'  Repositories: {len(r)}'); \
		print(f'  User: {u.get(\"username\", \"NOT SET\")}'); \
		print(f'  Slack: {\"configured\" if s.get(\"xoxc_token\") else \"NOT CONFIGURED\"}'); \
		"

# =============================================================================
# UTILITIES
# =============================================================================

status:
	@printf "\033[1mProcess Status:\033[0m\n"
	@printf "\n"
	@printf "\033[36mSlack Daemon:\033[0m\n"
	@$(MAKE) -s slack-daemon-status
	@printf "\n"
	@printf "\033[36mMCP Servers:\033[0m\n"
	@pgrep -f "src.server" > /dev/null && \
		echo -e "\033[32m✅ MCP server running\033[0m" || \
		echo -e "\033[33m⚠️  No MCP server running\033[0m"
	@printf "\n"

clean:
	@printf "\033[36mCleaning up...\033[0m\n"
	find $(PROJECT_ROOT) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(PROJECT_ROOT) -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -f $(SLACK_LOG) $(SLACK_PID) 2>/dev/null || true
	rm -f /tmp/slack-daemon.lock 2>/dev/null || true
	rm -f $(PROJECT_ROOT)/slack_state.db 2>/dev/null || true
	@printf "\033[32m✅ Cleaned\033[0m\n"

# =============================================================================
# PROJECT TOOLS (ptools)
# =============================================================================

# Sync AI rules from single source (docs/ai-rules/) to all targets
sync-ai-rules:
	@printf "\033[36mSyncing AI rules to all targets...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_ai_rules.py

sync-ai-rules-dry:
	@printf "\033[36mPreviewing AI rules sync (dry-run)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_ai_rules.py --dry-run

sync-ai-rules-verbose:
	@printf "\033[36mSyncing AI rules (verbose)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_ai_rules.py --verbose

sync-commands:
	@printf "\033[36mGenerating commands for new skills and syncing to Claude Code...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py --generate-missing
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py

sync-commands-dry:
	@printf "\033[36mPreviewing command sync (dry-run)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py --generate-missing --dry-run
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py --dry-run

sync-commands-reverse:
	@printf "\033[36mSyncing Claude Code commands to Cursor format...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py --reverse

sync-commands-generate:
	@printf "\033[36mGenerating Cursor commands for skills without commands...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_commands.py --generate-missing

sync-config-example:
	@printf "\033[36mChecking config.json.example has all keys...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_config_example.py -v

sync-config-example-fix:
	@printf "\033[36mAdding missing keys to config.json.example...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) ptools/sync_config_example.py --fix -v

# =============================================================================
# QUICK START
# =============================================================================

quick-start:
	@printf "\033[36m\033[1mQuick Start Guide\033[0m\n"
	@printf "\n"
	@printf "1. Copy and edit config:\n"
	@printf "   cp config.example.json config.json\n"
	@printf "   # Edit config.json with your Slack credentials\n"
	@printf "\n"
	@printf "2. Test credentials:\n"
	@printf "   make slack-test\n"
	@printf "\n"
	@printf "3. Run in dry-run mode:\n"
	@printf "   make slack-daemon-dry\n"
	@printf "\n"
	@printf "4. Run for real:\n"
	@printf "   make slack-daemon\n"
	@printf "\n"
	@printf "5. Run in background:\n"
	@printf "   make slack-daemon-bg\n"
	@printf "   make slack-daemon-logs\n"
	@printf "\n"

# =============================================================================
# VSCODE EXTENSION
# =============================================================================

EXT_DIR := $(PROJECT_ROOT)/extensions/aa-workflow-vscode
CURSOR_EXT_DIR := $(HOME)/.cursor/extensions

ext-build:
	@printf "\033[36mBuilding VSCode extension...\033[0m\n"
	cd $(EXT_DIR) && npm install && npm run compile
	@printf "\033[32m✅ Extension built\033[0m\n"

ext-install: ext-build
	@printf "\033[36mInstalling extension to Cursor...\033[0m\n"
	@mkdir -p $(CURSOR_EXT_DIR)
	@rm -rf $(CURSOR_EXT_DIR)/aa-workflow-vscode
	@ln -sf $(EXT_DIR) $(CURSOR_EXT_DIR)/aa-workflow-vscode
	@printf "\033[32m✅ Extension installed (symlinked)\033[0m\n"
	@printf "\033[33mRestart Cursor to activate the extension\033[0m\n"

ext-watch:
	@printf "\033[36mWatching extension for changes...\033[0m\n"
	cd $(EXT_DIR) && npm run watch

ext-clean:
	@printf "\033[36mCleaning extension build...\033[0m\n"
	rm -rf $(EXT_DIR)/out $(EXT_DIR)/node_modules
	@printf "\033[32m✅ Extension cleaned\033[0m\n"

ext-package:
	@printf "\033[36mPackaging extension...\033[0m\n"
	cd $(EXT_DIR) && npx --yes vsce package
	@printf "\033[32m✅ Extension packaged (see $(EXT_DIR)/*.vsix)\033[0m\n"
