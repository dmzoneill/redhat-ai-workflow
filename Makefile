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
        slack-status slack-pending slack-approve slack-approve-all slack-history \
        slack-send slack-watch slack-reload \
        mcp-server mcp-devops mcp-developer mcp-incident mcp-release \
        check-env

# Configuration
PYTHON := python3
PIP := pip3
PROJECT_ROOT := $(shell pwd)
VENV := $(PROJECT_ROOT)/.venv
SLACK_LOG := /tmp/slack-daemon.log
SLACK_PID := /tmp/slack-daemon.pid

# Colors for output
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m
BOLD := \033[1m

# Default target
.DEFAULT_GOAL := help

# =============================================================================
# HELP
# =============================================================================

help:
	@echo ""
	@echo "$(CYAN)$(BOLD)╔══════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(CYAN)$(BOLD)║  AI Workflow - Development & Runtime Commands                    ║$(RESET)"
	@echo "$(CYAN)$(BOLD)╚══════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@echo "$(BOLD)Slack Daemon:$(RESET)"
	@echo "  $(GREEN)make slack-daemon$(RESET)       Run Slack daemon (foreground, Ctrl+C to stop)"
	@echo "  $(GREEN)make slack-daemon-bg$(RESET)    Run Slack daemon (background with D-Bus)"
	@echo "  $(GREEN)make slack-daemon-stop$(RESET)  Stop background Slack daemon"
	@echo "  $(GREEN)make slack-daemon-logs$(RESET)  Tail Slack daemon logs"
	@echo "  $(GREEN)make slack-daemon-dry$(RESET)   Run in dry-run mode (no responses sent)"
	@echo "  $(GREEN)make slack-daemon-llm$(RESET)   Run with LLM integration enabled"
	@echo ""
	@echo "$(BOLD)Slack Control (D-Bus IPC):$(RESET)"
	@echo "  $(GREEN)make slack-status$(RESET)       Get daemon status and stats"
	@echo "  $(GREEN)make slack-pending$(RESET)      List messages awaiting approval"
	@echo "  $(GREEN)make slack-approve ID=xxx$(RESET)  Approve a specific message"
	@echo "  $(GREEN)make slack-approve-all$(RESET)  Approve all pending messages"
	@echo "  $(GREEN)make slack-history$(RESET)      Show message history"
	@echo "  $(GREEN)make slack-watch$(RESET)        Watch for new messages (live)"
	@echo "  $(GREEN)make slack-reload$(RESET)       Reload daemon configuration"
	@echo "  $(GREEN)make slack-send$(RESET)         Send message (TARGET=C.../U.../@user MSG=...)"
	@echo ""
	@echo "$(BOLD)MCP Servers:$(RESET)"
	@echo "  $(GREEN)make mcp-server$(RESET)         Run MCP server (default: developer)"
	@echo "  $(GREEN)make mcp-developer$(RESET)      Run developer agent"
	@echo "  $(GREEN)make mcp-devops$(RESET)         Run devops agent"
	@echo "  $(GREEN)make mcp-incident$(RESET)       Run incident agent"
	@echo "  $(GREEN)make mcp-release$(RESET)        Run release agent"
	@echo "  $(GREEN)make mcp-slack$(RESET)          Run slack agent"
	@echo "  $(GREEN)make mcp-all$(RESET)            Run with ALL tools (may exceed limits)"
	@echo ""
	@echo "$(BOLD)Development:$(RESET)"
	@echo "  $(GREEN)make install$(RESET)            Install dependencies"
	@echo "  $(GREEN)make test$(RESET)               Run tests"
	@echo "  $(GREEN)make lint$(RESET)               Run linters (flake8, black --check)"
	@echo "  $(GREEN)make format$(RESET)             Auto-format code with black"
	@echo "  $(GREEN)make check-env$(RESET)          Validate environment variables"
	@echo ""
	@echo "$(BOLD)Utilities:$(RESET)"
	@echo "  $(GREEN)make clean$(RESET)              Clean temporary files"
	@echo "  $(GREEN)make status$(RESET)             Show status of running processes"
	@echo ""

# =============================================================================
# INSTALLATION
# =============================================================================

install:
	@echo "$(CYAN)Installing dependencies...$(RESET)"
	$(PIP) install -r requirements.txt 2>/dev/null || \
		$(PIP) install fastmcp pyyaml httpx jinja2 python-dotenv aiosqlite pydantic
	@echo "$(GREEN)✅ Dependencies installed$(RESET)"

install-dev: install
	@echo "$(CYAN)Installing dev dependencies...$(RESET)"
	$(PIP) install pytest pytest-asyncio black flake8 isort
	@echo "$(GREEN)✅ Dev dependencies installed$(RESET)"

# =============================================================================
# SLACK DAEMON
# =============================================================================

check-env:
	@echo "$(CYAN)Checking environment...$(RESET)"
	@if [ -z "$$SLACK_XOXC_TOKEN" ]; then \
		echo "$(RED)❌ SLACK_XOXC_TOKEN not set$(RESET)"; \
		echo "   Get it from browser dev tools while logged into Slack"; \
		exit 1; \
	else \
		echo "$(GREEN)✅ SLACK_XOXC_TOKEN set$(RESET)"; \
	fi
	@if [ -z "$$SLACK_D_COOKIE" ]; then \
		echo "$(RED)❌ SLACK_D_COOKIE not set$(RESET)"; \
		echo "   Get it from browser dev tools (Cookie header, 'd' value)"; \
		exit 1; \
	else \
		echo "$(GREEN)✅ SLACK_D_COOKIE set$(RESET)"; \
	fi
	@if [ -z "$$SLACK_WATCHED_CHANNELS" ]; then \
		echo "$(YELLOW)⚠️  SLACK_WATCHED_CHANNELS not set (will monitor nothing)$(RESET)"; \
	else \
		echo "$(GREEN)✅ SLACK_WATCHED_CHANNELS set$(RESET)"; \
	fi
	@echo ""

slack-daemon: check-env
	@echo "$(CYAN)Starting Slack daemon (foreground)...$(RESET)"
	@echo "$(YELLOW)Press Ctrl+C to stop$(RESET)"
	@echo ""
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py

slack-daemon-verbose: check-env
	@echo "$(CYAN)Starting Slack daemon (verbose)...$(RESET)"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --verbose

slack-daemon-dry: check-env
	@echo "$(CYAN)Starting Slack daemon (dry-run mode)...$(RESET)"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --dry-run --verbose

slack-daemon-llm: check-env
	@echo "$(CYAN)Starting Slack daemon with LLM...$(RESET)"
	@if [ -z "$$OPENAI_API_KEY" ]; then \
		echo "$(YELLOW)⚠️  OPENAI_API_KEY not set, LLM features disabled$(RESET)"; \
	fi
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --llm

slack-daemon-stop:
	@if [ -f $(SLACK_PID) ]; then \
		PID=$$(cat $(SLACK_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "$(CYAN)Stopping daemon (PID: $$PID)...$(RESET)"; \
			kill $$PID; \
			rm -f $(SLACK_PID); \
			echo "$(GREEN)✅ Daemon stopped$(RESET)"; \
		else \
			echo "$(YELLOW)⚠️  Process not running$(RESET)"; \
			rm -f $(SLACK_PID); \
		fi; \
	else \
		echo "$(YELLOW)⚠️  No PID file found$(RESET)"; \
	fi

slack-daemon-logs:
	@if [ -f $(SLACK_LOG) ]; then \
		echo "$(CYAN)Tailing $(SLACK_LOG)...$(RESET)"; \
		tail -f $(SLACK_LOG); \
	else \
		echo "$(YELLOW)⚠️  No log file found$(RESET)"; \
	fi

slack-daemon-status:
	@if [ -f $(SLACK_PID) ] && kill -0 $$(cat $(SLACK_PID)) 2>/dev/null; then \
		echo "$(GREEN)✅ Daemon running (PID: $$(cat $(SLACK_PID)))$(RESET)"; \
	else \
		echo "$(YELLOW)⚠️  Daemon not running$(RESET)"; \
	fi

# D-Bus daemon with IPC enabled
slack-daemon-dbus: check-env
	@echo "$(CYAN)Starting Slack daemon with D-Bus IPC...$(RESET)"
	cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_daemon.py --dbus

slack-daemon-bg: check-env
	@echo "$(CYAN)Starting Slack daemon (background with D-Bus)...$(RESET)"
	@if [ -f $(SLACK_PID) ] && kill -0 $$(cat $(SLACK_PID)) 2>/dev/null; then \
		echo "$(YELLOW)⚠️  Daemon already running (PID: $$(cat $(SLACK_PID)))$(RESET)"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && \
		nohup $(PYTHON) scripts/slack_daemon.py --dbus > $(SLACK_LOG) 2>&1 & \
		echo $$! > $(SLACK_PID)
	@sleep 2
	@echo "$(GREEN)✅ Daemon started (PID: $$(cat $(SLACK_PID)))$(RESET)"
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
		echo "$(RED)❌ Usage: make slack-approve ID=<message_id>$(RESET)"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py approve $(ID)

slack-approve-all:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py approve-all

slack-reject:
	@if [ -z "$(ID)" ]; then \
		echo "$(RED)❌ Usage: make slack-reject ID=<message_id>$(RESET)"; \
		exit 1; \
	fi
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py reject $(ID)

slack-history:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py history -n 50 -v

slack-watch:
	@echo "$(CYAN)Watching for new messages (Ctrl+C to stop)...$(RESET)"
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py watch

slack-reload:
	@cd $(PROJECT_ROOT) && $(PYTHON) scripts/slack_control.py reload

slack-send:
	@TARGET_VAL=$${TARGET:-$$CHANNEL}; \
	if [ -z "$$TARGET_VAL" ] || [ -z "$(MSG)" ]; then \
		echo "$(RED)❌ Usage:$(RESET)"; \
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
	@echo "$(CYAN)Starting MCP server (developer agent)...$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent developer

mcp-devops:
	@echo "$(CYAN)Starting MCP server (devops agent)...$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent devops

mcp-incident:
	@echo "$(CYAN)Starting MCP server (incident agent)...$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent incident

mcp-release:
	@echo "$(CYAN)Starting MCP server (release agent)...$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent release

mcp-slack:
	@echo "$(CYAN)Starting MCP server (slack agent)...$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --agent slack

mcp-all:
	@echo "$(YELLOW)⚠️  Loading ALL tools - may exceed Cursor's 128 tool limit!$(RESET)"
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --all

mcp-custom:
	@echo "$(CYAN)Usage: make mcp-custom TOOLS='git,jira,slack'$(RESET)"
	@if [ -z "$(TOOLS)" ]; then \
		echo "$(RED)❌ TOOLS not specified$(RESET)"; \
		exit 1; \
	fi
	cd $(PROJECT_ROOT)/mcp-servers/aa-common && $(PYTHON) -m src.server --tools $(TOOLS)

# =============================================================================
# DEVELOPMENT
# =============================================================================

test:
	@echo "$(CYAN)Running tests...$(RESET)"
	cd $(PROJECT_ROOT) && $(PYTHON) -m pytest tests/ -v

lint:
	@echo "$(CYAN)Running linters...$(RESET)"
	cd $(PROJECT_ROOT) && flake8 scripts/ mcp-servers/ --max-line-length=100 --ignore=E501,W503
	cd $(PROJECT_ROOT) && black --check scripts/ mcp-servers/
	@echo "$(GREEN)✅ Linting passed$(RESET)"

format:
	@echo "$(CYAN)Formatting code...$(RESET)"
	cd $(PROJECT_ROOT) && black scripts/ mcp-servers/ --line-length=100
	@echo "$(GREEN)✅ Code formatted$(RESET)"

# =============================================================================
# UTILITIES
# =============================================================================

status:
	@echo "$(BOLD)Process Status:$(RESET)"
	@echo ""
	@echo "$(CYAN)Slack Daemon:$(RESET)"
	@$(MAKE) -s slack-daemon-status
	@echo ""
	@echo "$(CYAN)MCP Servers:$(RESET)"
	@pgrep -f "src.server" > /dev/null && \
		echo "$(GREEN)✅ MCP server running$(RESET)" || \
		echo "$(YELLOW)⚠️  No MCP server running$(RESET)"
	@echo ""

clean:
	@echo "$(CYAN)Cleaning up...$(RESET)"
	find $(PROJECT_ROOT) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(PROJECT_ROOT) -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -f $(SLACK_LOG) $(SLACK_PID) 2>/dev/null || true
	rm -f $(PROJECT_ROOT)/mcp-servers/aa-slack/slack_state.db 2>/dev/null || true
	@echo "$(GREEN)✅ Cleaned$(RESET)"

# =============================================================================
# QUICK START
# =============================================================================

quick-start:
	@echo "$(CYAN)$(BOLD)Quick Start Guide$(RESET)"
	@echo ""
	@echo "1. Set environment variables:"
	@echo "   export SLACK_XOXC_TOKEN='xoxc-...'"
	@echo "   export SLACK_D_COOKIE='...'"
	@echo "   export SLACK_WATCHED_CHANNELS='C12345678,C87654321'"
	@echo "   export SLACK_WATCHED_KEYWORDS='help,question'"
	@echo "   export SLACK_SELF_USER_ID='U12345678'"
	@echo ""
	@echo "2. Test with dry-run:"
	@echo "   make slack-daemon-dry"
	@echo ""
	@echo "3. Run for real:"
	@echo "   make slack-daemon"
	@echo ""
	@echo "4. Run in background:"
	@echo "   make slack-daemon-bg"
	@echo "   make slack-daemon-logs"
	@echo ""

