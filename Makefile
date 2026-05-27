# Variables
SHELL := /bin/bash
PYTHON := python3
.DEFAULT_GOAL := help


.PHONY: help
help: ## Display this help menu with detailed target descriptions
	@echo ""
	@echo -e "  \033[1;35mTemporal-SVDL Development Management Tool\033[0m"
	@echo "  ========================================="
	@echo ""
	@echo -e "  \033[1mUsage:\033[0m"
	@echo -e "    make \033[36m<target>\033[0m [options]"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "  \033[1mTargets:\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "    \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n  \033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)
	@echo ""


.PHONY: setup
setup: env ## Initialize virtual environment and install all dependencies (including dev)
	@echo "Initializing virtual environment and syncing dependencies..."
	uv sync --all-extras
	@echo "Setup complete! The virtual environment '.venv' is fully synchronized."

.PHONY: env
env: ## Create the .env file from .env.example if it doesn't already exist
	@if [ -f .env ]; then \
		echo ".env file already exists. Skipping copy."; \
	else \
		echo "Creating .env file from template (.env.example)..."; \
		cp .env.example .env; \
		echo "Please update .env with your Google Maps API Key."; \
	fi

.PHONY: update-deps
update-deps: ## Update dependency resolution and sync lockfile
	@echo "Updating dependencies..."
	uv lock --upgrade
	uv sync --all-extras

.PHONY: lint
lint: ## Run Ruff check to inspect code quality and style issues
	@echo "Running Ruff code analysis..."
	@uv run ruff check src/ tests/

.PHONY: format
format: ## Format source and test code automatically using Ruff
	@echo "Formatting code style..."
	@uv run ruff format src/ tests/

.PHONY: lint-fix
lint-fix: ## Run Ruff and automatically resolve auto-fixable issues
	@echo "Auto-fixing code style and imports..."
	@uv run ruff check --fix src/ tests/

.PHONY: check
check: ## Run format, lint-fix, and test suites (pre-commit quality check)
	@echo "Running comprehensive project validation..."
	@$(MAKE) format
	@$(MAKE) lint-fix
	@$(MAKE) test

.PHONY: test
test: ## Run the entire test suite using Pytest
	@echo "Running project tests..."
	@uv run pytest --color=yes

.PHONY: test-cov
test-cov: ## Run tests and print a code coverage report for the source module
	@echo "Running tests with coverage estimation..."
	@uv run pytest --cov=src --cov-report=term-missing tests/

.PHONY: clean
clean: ## Remove temporary python artifacts and pycache folders
	@echo "Cleaning Python pycache and build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "*.egg" -exec rm -rf {} +
	@echo "Cleanup finished."

.PHONY: deep-clean
deep-clean: clean clean-logs ## Comprehensive reset: removes virtualenv, cache dirs, build bundles, and logs
	@echo "Executing deep cleaning..."
	rm -rf .venv
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf dist
	rm -rf build
	@echo "Deep clean complete! Workspace reset."

.PHONY: clean-logs
clean-logs: ## Clean logs
	rm -rf logs/
