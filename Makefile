# MCP Workshop - Development Commands
# ====================================

# Nothing here benefits from parallel make - the work is docker and network
# calls - and `diagrams` writes shared output files that would race under -j.
.NOTPARALLEL:

.PHONY: help check-env setup quickstart \
	up up-build down restart status health \
	logs logs-mcp logs-agent logs-web \
	build build-mcp build-agent build-web \
	shell-mcp shell-agent shell-web clean \
	curl-discover curl-list curl-weather curl-agent \
	curl-mismatch curl-nometa curl-badversion curl-unknown curl-origin \
	curl-fact curl-fact-agent curl-news curl-news-agent curl-combo \
	test test-protocol test-compliance \
	diagrams diagrams-force slides docs-server serve-slides \
	db-view db-shell db-reset db-stats

# Default target
help: ## Show this help
	@echo "MCP Workshop Commands"
	@echo "====================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================================
# Docker Compose
# ============================================================================

check-env: ## Verify .env is in step with .env.example
	@./helper/check-env

# The `-` makes a failed check print its diagnosis without blocking startup.
# Lab 1 is pure curl against the MCP server and needs no LLM key at all, so
# refusing to start would cost workshop minutes to prevent a problem that
# announces itself loudly the moment someone sends a query.
up: ## Start all services
	@-./helper/check-env
	docker compose up -d

up-build: ## Start all services with rebuild
	@-./helper/check-env
	docker compose up -d --build

# `--profile datasette` on the way down, not just up: `docker compose down`
# ignores services whose profile is not active, so once someone has run
# `make db-view`, a plain `down` would leave Datasette running and holding the
# network open. Stopping more than you started is the safe direction here.
down: ## Stop all services
	docker compose --profile datasette down

restart: ## Restart all services
	docker compose restart

logs: ## Follow logs from all services
	docker compose logs -f

logs-mcp: ## Follow MCP server logs
	docker compose logs -f mcp-server

logs-agent: ## Follow agent logs
	docker compose logs -f travel-agent

logs-web: ## Follow web logs
	docker compose logs -f agent-web

status: ## Show service status
	@echo "=== Container Status ==="
	@docker compose ps
	@echo ""
	@echo "=== Health Status ==="
	@curl -s http://localhost:8000/health 2>/dev/null && echo " ✓ MCP Server (8000)" || echo " ✗ MCP Server (8000)"
	@curl -s http://localhost:8001/health 2>/dev/null && echo " ✓ Agent (8001)" || echo " ✗ Agent (8001)"
	@curl -s http://localhost:8080/health 2>/dev/null && echo " ✓ Web (8080)" || echo " ✗ Web (8080)"

health: ## Check health of all services
	@echo "MCP Server:"; curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "  Not responding"
	@echo "Agent:"; curl -s http://localhost:8001/health | python3 -m json.tool 2>/dev/null || echo "  Not responding"
	@echo "Web:"; curl -s http://localhost:8080/health | python3 -m json.tool 2>/dev/null || echo "  Not responding"

# ============================================================================
# Development
# ============================================================================

build: ## Build all Docker images
	docker compose build

build-mcp: ## Build MCP server image
	docker compose build mcp-server

build-agent: ## Build agent image
	docker compose build travel-agent

build-web: ## Build web image
	docker compose build agent-web

shell-mcp: ## Open shell in MCP server container
	docker compose exec mcp-server /bin/sh

shell-agent: ## Open shell in agent container
	docker compose exec travel-agent /bin/sh

shell-web: ## Open shell in web container
	docker compose exec agent-web /bin/sh

clean: ## Remove containers, volumes, networks and local images
	@echo "=== Stopping this project ==="
	-@docker compose --profile datasette down -v --remove-orphans --rmi local 2>/dev/null || true
	@echo "=== Clearing older project names ==="
	@# The project name is the directory name, `mcp-lab-jz26-final`, and the
	@# `down` above already covers it. Earlier checkouts ran as `mcp-workshop`
	@# (an old COMPOSE_PROJECT_NAME) and `mcp-lab-jz26` (an earlier directory),
	@# so resources may linger under those. Clearing them is what makes this
	@# recover from the container-name conflict.
	-@docker compose -p mcp-workshop down -v --remove-orphans 2>/dev/null || true
	-@docker compose -p mcp-lab-jz26 down -v --remove-orphans 2>/dev/null || true
	@echo "=== Removing stale containers by name ==="
	@# `container_name` is global, not project-scoped, so one left-over
	@# container blocks startup no matter which project you use.
	-@ids=$$(docker ps -aq --filter "name=travel-weather-"); \
	  if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "  none"; fi
	-@docker network rm travel-weather-network 2>/dev/null || true
	@# Legacy: volumes used to carry an explicit global `name:`. They outlive
	@# `down -v`, which only removes project-scoped ones.
	-@docker volume rm travel-weather-logs travel-weather-agent-data 2>/dev/null || true
	@echo "Clean. Run 'make up-build' to start again."

# ============================================================================
# Testing - LAB 1: Explore Tools
# ============================================================================

MCP := ./helper/mcp-curl

curl-discover: ## LAB1: Server identity, versions and capabilities (server/discover)
	@echo "=== server/discover ==="
	@$(MCP) server/discover

curl-list: ## LAB1: List available MCP tools (tools/list)
	@echo "=== tools/list ==="
	@$(MCP) tools/list

curl-weather: ## LAB1: Test weather tool directly (tools/call)
	@echo "=== get_weather_forecast for Oslo ==="
	@$(MCP) tools/call '{"name":"get_weather_forecast","arguments":{"location":"Oslo"}}'

curl-agent: ## LAB1: Test query through agent
	@echo "=== Querying agent about weather ==="
	@curl -s -X POST "http://localhost:8001/query" \
		-H "Content-Type: application/json" \
		-d '{"query": "What is the weather in Bergen?"}' | python3 -m json.tool

# ============================================================================
# Testing - protocol violations
#
# The fastest way to understand the 2026-07-28 rules is to break them and
# watch which status code comes back. Each of these should FAIL, and the way
# it fails is the point.
# ============================================================================

curl-mismatch: ## PROTO: Mcp-Method header disagrees with the body -> 400 / -32020
	@echo "=== Header/body mismatch (expect 400 + -32020) ==="
	@curl -s -X POST "http://localhost:8000/message" \
		-H "Content-Type: application/json" \
		-H "MCP-Protocol-Version: 2026-07-28" \
		-H "Mcp-Method: tools/call" \
		-d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}' \
		-w '\nHTTP %{http_code}\n'

curl-nometa: ## PROTO: no params._meta -> 400 / -32602
	@echo "=== Missing _meta (expect 400 + -32602) ==="
	@curl -s -X POST "http://localhost:8000/message" \
		-H "Content-Type: application/json" \
		-H "MCP-Protocol-Version: 2026-07-28" \
		-H "Mcp-Method: tools/list" \
		-d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
		-w '\nHTTP %{http_code}\n'

curl-badversion: ## PROTO: unsupported protocol version -> 400 / -32022 + data.supported
	@echo "=== Unsupported version (expect 400 + -32022) ==="
	@MCP_VERSION=2025-11-25 $(MCP) tools/list

curl-unknown: ## PROTO: unknown method -> 404, not 200
	@echo "=== Unknown method (expect 404 + -32601) ==="
	@$(MCP) resources/list

curl-origin: ## PROTO: untrusted Origin -> 403 (DNS rebinding protection)
	@echo "=== Untrusted Origin (expect 403) ==="
	@MCP_ORIGIN=https://evil.example.com $(MCP) tools/list

# ============================================================================
# Testing - LAB 2: Random Fact Tool
# ============================================================================

curl-fact: ## LAB2: Test random fact tool (after implementation)
	@echo "=== get_random_fact ==="
	@$(MCP) tools/call '{"name":"get_random_fact","arguments":{"category":"space"}}'

curl-fact-agent: ## LAB2: Test fact tool via agent
	@echo "=== Querying agent for a fact ==="
	@curl -s -X POST "http://localhost:8001/query" \
		-H "Content-Type: application/json" \
		-d '{"query": "Tell me an interesting fact about space"}' | python3 -m json.tool

# ============================================================================
# Testing - LAB 3: News (Google News RSS, no key)
# ============================================================================

curl-news: ## LAB3: Test news tool (after implementation)
	@echo "=== get_news ==="
	@$(MCP) tools/call '{"name":"get_news","arguments":{"topic":"Oslo travel","language":"en"}}'

curl-news-agent: ## LAB3: Test news via agent
	@echo "=== Querying agent for news ==="
	@curl -s -X POST "http://localhost:8001/query" \
		-H "Content-Type: application/json" \
		-d '{"query": "What is the latest news about artificial intelligence?"}' | python3 -m json.tool

# ============================================================================
# Combined Tests
# ============================================================================

curl-combo: ## Test combining multiple tools
	@echo "=== Querying agent with multiple tools ==="
	@curl -s -X POST "http://localhost:8001/query" \
		-H "Content-Type: application/json" \
		-d '{"query": "What is the weather in Oslo, and tell me a fact about space"}' | python3 -m json.tool

# ============================================================================
# Compliance Testing
# ============================================================================

test-protocol: ## Run the MCP protocol tests (in-process, no network)
	@echo "=== Protocol tests: error codes paired with status codes ==="
	@docker compose exec -T mcp-server python -m pytest test_mcp_protocol.py -q -W ignore::DeprecationWarning

test-compliance: ## Run MCP SDK compliance test (official mcp 2.0.0 SDK)
	docker compose --profile compliance-test up mcp-sdk-client

test: test-protocol test-compliance ## Run both test suites

# ============================================================================
# Documentation
# ============================================================================

MMD := $(wildcard doc/diagrams/*.mmd)
DIAGRAMS := $(MMD:.mmd=.png)

doc/diagrams/%.png: doc/diagrams/%.mmd
	@echo "=== Rendering $< ==="
	@npx -y -p @mermaid-js/mermaid-cli mmdc -i $< -o $@ -b '#1e1e1e' -s 2

diagrams: $(DIAGRAMS) ## Render the architecture diagrams from Mermaid source
	@echo "Done: $(DIAGRAMS)"

diagrams-force: ## Re-render every diagram, ignoring timestamps
	@touch $(MMD) && $(MAKE) diagrams

# Use a locally installed marp if there is one, otherwise fetch the CLI with npx.
MARP := $(shell command -v marp 2>/dev/null || echo "npx --yes @marp-team/marp-cli")

slides: diagrams ## Build the presentation HTML from the Markdown deck
	@$(MARP) --no-stdin doc/ws-pres-cut.md -o doc/ws-pres-cut.html --html --allow-local-files
	@echo "Note: the HTML references doc/diagrams/ relatively - keep them together."

docs-server: slides ## Serve doc/, rebuilding the deck whenever a source changes
	@./helper/docs-server

serve-slides: docs-server ## Alias for docs-server

# ============================================================================
# Database
# ============================================================================

db-shell: ## Open a SQL shell on the conversation database (no extra container)
	@echo "=== SQLite shell on /data/conversations.db ==="
	@# Python 3.12+ ships a SQLite REPL, so this needs nothing that is not
	@# already in the agent image - no sqlite3 CLI, no Datasette, no download.
	@echo "Note: this REPL has no .tables or .schema. Use SQL instead:"
	@echo "  select name from sqlite_master where type='table';"
	@echo "  select sql from sqlite_master where name='conversations';"
	@echo "Ctrl-D or .quit to exit."
	@echo ""
	@docker compose exec travel-agent python3 -m sqlite3 /data/conversations.db

db-view: ## Open Datasette to browse the conversation database in a browser
	@# Datasette sits behind a profile, so this is what pulls and starts it.
	@# First run downloads 324MB; after that it is instant.
	docker compose --profile datasette up -d datasette
	@echo "Datasette at http://localhost:8090"
	@sleep 2
	@open http://localhost:8090 2>/dev/null || echo "Visit http://localhost:8090"

db-reset: ## Wipe the conversation database and start a fresh session
	@# Delete the file rather than DELETE the rows: the schema is created with
	@# CREATE TABLE IF NOT EXISTS at start-up, so a restart rebuilds it clean.
	@# The restart matters for a second reason - the agent holds one session id
	@# in memory from start-up, so wiping `sessions` under a running agent would
	@# leave it writing messages against a session row that no longer exists.
	@printf "This deletes all conversation history. Continue? [y/N] " && \
	  read ans && [ "$$ans" = "y" ] || { echo "Cancelled."; exit 1; }
	@docker compose exec -T travel-agent rm -f /data/conversations.db
	@docker compose restart travel-agent
	@echo "Database reset. The agent rebuilt the schema and opened a new session."

db-stats: ## Show database statistics
	@# Both arguments matter. The method is get_database_stats, not get_stats.
	@# And ConversationMemory() defaults to a *relative* data/conversations.db,
	@# so without the path it would silently create an empty database in the
	@# container's working directory and report zeros for it.
	@docker compose exec -T travel-agent python3 -c "\
from conversation_memory import ConversationMemory; \
s = ConversationMemory('/data/conversations.db').get_database_stats(); \
print('\n'.join(f'  {k}: {v}' for k, v in s.items()))"

# ============================================================================
# Quick Start
# ============================================================================

setup: ## Initial setup (copy .env.example to .env)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
		echo "Please edit .env and add your API keys:"; \
		echo "  - OPENAI_API_KEY"; \
		echo "  (Weather data uses yr.no - no API key needed)"; \
	else \
		echo ".env already exists"; \
	fi

quickstart: setup up status ## Full quickstart: setup + start + status
	@echo ""
	@echo "=== Workshop Ready ==="
	@echo "Web UI: http://localhost:8080"
	@echo ""
	@echo "Try these commands:"
	@echo "  make curl-list     # List available tools"
	@echo "  make curl-weather  # Test weather tool"
	@echo "  make curl-agent    # Query through agent"
