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

.PHONY: help install test lint format clean \
        slack-daemon slack-daemon-bg slack-daemon-stop slack-daemon-logs \
        slack-daemon-verbose slack-daemon-dry slack-daemon-llm slack-daemon-llm-verbose \
        slack-status slack-pending slack-approve slack-approve-all slack-history \
        slack-send slack-watch slack-reload \
        mcp-server mcp-devops mcp-developer mcp-incident mcp-release \
        check-env

# Use bash for proper escape sequence handling
SHELL := /bin/bash

# Configuration
PYTHON := python3
PIP := pip3
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
	@printf "  \033[32mmake slack-daemon-dry\033[0m   Run in dry-run mode (no responses sent)\n"
	@printf "  \033[32mmake slack-daemon-llm\033[0m   Run with LLM (Claude) integration\n"
	@printf "  \033[32mmake slack-daemon-llm-verbose\033[0m  Run with LLM + verbose logging\n"
	@printf "\n"
	@printf "\033[1mSlack Control (D-Bus IPC):\033[0m\n"
	@printf "  \033[32mmake slack-status\033[0m       Get daemon status and stats\n"
	@printf "  \033[32mmake slack-pending\033[0m      List messages awaiting approval\n"
	@printf "  \033[32mmake slack-approve ID=xxx\033[0m  Approve a specific message\n"
	@printf "  \033[32mmake slack-approve-all\033[0m  Approve all pending messages\n"
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
	@printf "\n"
	@printf "\033[1mDevelopment:\033[0m\n"
	@printf "  \033[32mmake install\033[0m            Install dependencies\n"
	@printf "  \033[32mmake test\033[0m               Run tests\n"
	@printf "  \033[32mmake lint\033[0m               Run linters (flake8, black --check)\n"
	@printf "  \033[32mmake format\033[0m             Auto-format code with black\n"
	@printf "  \033[32mmake check-env\033[0m          Validate environment variables\n"
	@printf "\n"
	@printf "\033[1mUtilities:\033[0m\n"
	@printf "  \033[32mmake clean\033[0m              Clean temporary files\n"
	@printf "  \033[32mmake status\033[0m             Show status of running processes\n"
	@printf "\n"

# =============================================================================
# INSTALLATION
# =============================================================================

install:
	@printf "\033[36mInstalling dependencies...\033[0m\n"
	$(PIP) install -r requirements.txt 2>/dev/null || \
		$(PIP) install fastmcp pyyaml httpx jinja2 python-dotenv aiosqlite pydantic
	@printf "\033[32m✅ Dependencies installed\033[0m\n"

install-dev: install
	@printf "\033[36mInstalling dev dependencies...\033[0m\n"
	$(PIP) install pytest pytest-asyncio black flake8 isort
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

slack-daemon-llm: check-env
	@printf "\033[36mStarting Slack daemon with LLM...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --llm

slack-daemon-llm-verbose: check-env
	@printf "\033[36mStarting Slack daemon with LLM (verbose)...\033[0m\n"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --llm --verbose

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
	@echo "   D-Bus: com.aiworkflow.SlackAgent"
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
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent developer

mcp-devops:
	@printf "\033[36mStarting MCP server (devops agent)...\033[0m\n"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent devops

mcp-incident:
	@printf "\033[36mStarting MCP server (incident agent)...\033[0m\n"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent incident

mcp-release:
	@printf "\033[36mStarting MCP server (release agent)...\033[0m\n"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent release

mcp-slack:
	@printf "\033[36mStarting MCP server (slack agent)...\033[0m\n"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent slack

mcp-all:
	@printf "\033[33m⚠️  Loading ALL tools - may exceed Cursor's 128 tool limit!\033[0m\n"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --all

mcp-custom:
	@printf "\033[36mUsage: make mcp-custom TOOLS='git,jira,slack'\033[0m\n"
	@if [ -z "$(TOOLS)" ]; then \
		echo -e "\033[31m❌ TOOLS not specified\033[0m"; \
		exit 1; \
	fi
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --tools $(TOOLS)

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
	cd $(PROJECT_ROOT) && flake8 scripts/ mcp-servers/ --max-line-length=100 --ignore=E501,W503
	cd $(PROJECT_ROOT) && black --check scripts/ mcp-servers/
	@printf "\033[32m✅ Linting passed\033[0m\n"

format:
	@printf "\033[36mFormatting code...\033[0m\n"
	cd $(PROJECT_ROOT) && black scripts/ mcp-servers/ --line-length=100
	@printf "\033[32m✅ Code formatted\033[0m\n"

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
