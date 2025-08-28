# ====================================================================================
#
#   Wake up, Neo...
#   The Matrix has you. Follow the white rabbit.
#
#   This Makefile automates the construct program.
#   Run `make help` to see available programs.
#
# ====================================================================================

# // ---[ System & Environment ]--- //
.ONESHELL:
.DEFAULT_GOAL := help

# // ---[ Variables & Constants ]--- //
PY_BOOT       := $(shell command -v python3.11 || command -v python3 || command -v python)
VENV_DIR      := .venv
PYTHON        := $(VENV_DIR)/bin/python
VENV_MARKER   := $(VENV_DIR)/.installed
SRC_DIR       := matrix_cli
TEST_DIR      := tests
BUILD_DIR     := dist

# Which extras to install from the construct:
#   dev  = full agent toolchain (tests, lint, format, typecheck, build, publish, docs)
#   test = combat training only (pytest, pytest-cov, pytest-mock)
EXTRAS        ?= dev

# Terminal colors for the Matrix display
BRIGHT_GREEN  := $(shell tput -T screen setaf 10)
DIM_GREEN     := $(shell tput -T screen setaf 2)
RESET         := $(shell tput -T screen sgr0)

# // ---[ Core Programs ]--- //

.PHONY: help
help: ## 🐇 Follow the white rabbit (show this help message)
	@echo
	@echo "$(BRIGHT_GREEN)TRANSMISSION INCOMING...$(RESET)"
	@echo "Usage: make <program>"
	@echo
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  $(BRIGHT_GREEN)%-20s$(RESET) $(DIM_GREEN)%s$(RESET)\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

.PHONY: setup
setup: .venv/pyvenv.cfg ## 🔌 Jack into the Matrix (create .venv)

.venv/pyvenv.cfg:
	@echo "$(DIM_GREEN)-> Jacking in... constructing virtual environment in $(VENV_DIR)...$(RESET)"
	@$(PY_BOOT) -m venv $(VENV_DIR)

# Install dependencies (or when the construct changes)
$(VENV_MARKER): .venv/pyvenv.cfg pyproject.toml
	@echo "$(DIM_GREEN)-> Loading programs... installing dependencies (extras: $(EXTRAS))...$(RESET)"
	@$(PYTHON) -m pip install -q --upgrade pip setuptools wheel
	@$(PYTHON) -m pip install -e ".[$(EXTRAS)]"
	@touch $@

.PHONY: install
install: $(VENV_MARKER) ## 💉 Inject programs (force re-install dependencies)
	@echo "$(DIM_GREEN)-> Re-injecting local programs (extras: $(EXTRAS))...$(RESET)"
	@$(PYTHON) -m pip install --force-reinstall --no-deps -e ".[$(EXTRAS)]"

# Convenience: install combat training tools only
.PHONY: install-test-tools
install-test-tools: .venv/pyvenv.cfg ## 🥋 Load combat training tools only
	@echo "$(DIM_GREEN)-> Loading combat training extras...$(RESET)"
	@$(PYTHON) -m pip install -q --upgrade pip setuptools wheel
	@$(PYTHON) -m pip install -e ".[test]"

# // ---[ Quality Control Unit ]--- //

.PHONY: fmt
fmt: $(VENV_MARKER) ## 🥄 Bend the code (format with Black and Ruff)
	@echo "$(DIM_GREEN)-> Re-aligning code constructs...$(RESET)"
	@$(PYTHON) -m black $(SRC_DIR) $(TEST_DIR)
	@$(PYTHON) -m ruff format $(SRC_DIR) $(TEST_DIR)

.PHONY: lint
lint: $(VENV_MARKER) ## 🕶️  Scan for Agents (lint with Ruff and Flake8)
	@echo "$(DIM_GREEN)-> Scanning for Agents...$(RESET)"
	@$(PYTHON) -m ruff check $(SRC_DIR) $(TEST_DIR)
	@$(PYTHON) -m flake8 $(SRC_DIR) $(TEST_DIR)

.PHONY: typecheck
typecheck: $(VENV_MARKER) ## 💊 Choose your pill (run Mypy for static type checking)
	@echo "$(DIM_GREEN)-> Verifying reality constructs...$(RESET)"
	@$(PYTHON) -m mypy $(SRC_DIR)

.PHONY: qa
qa: fmt lint typecheck ## 💯 Become The One (run all QA checks)

# // ---[ Simulation & Training ]--- //

# IMPORTANT: Do not depend on $(VENV_MARKER) so running tests won't reinstall anything.
.PHONY: test
test: .venv/pyvenv.cfg ## 🥋 Enter the Dojo (run tests with Pytest)
	@echo "$(DIM_GREEN)-> Entering the Dojo... initiating simulations...$(RESET)"
	@if [ ! -x "$(VENV_DIR)/bin/pytest" ]; then \
		echo "$(BRIGHT_GREEN)!! Training program 'pytest' not found. Run 'make install' to load it.$(RESET)"; \
		exit 1; \
	fi
	@$(VENV_DIR)/bin/pytest --maxfail=1

# // ---[ Build & Broadcast ]--- //

.PHONY: build
build: $(VENV_MARKER) ## 🏗️  Construct the residual self-image (build packages)
	@echo "$(DIM_GREEN)-> Compiling residual self-image... building distribution packages...$(RESET)"
	@rm -rf $(BUILD_DIR) build
	@$(PYTHON) -m build

.PHONY: publish
publish: build ## 📡 Broadcast to Zion (upload packages to PyPI)
	@echo "$(DIM_GREEN)-> Broadcasting to the Zion mainframe (PyPI)...$(RESET)"
	@$(PYTHON) -m twine upload $(BUILD_DIR)/*

# // ---[ Local Construct Builder ]--- //

.PHONY: wheels build-wheels
wheels build-wheels: .venv/pyvenv.cfg ## 🧱 Build local constructs (wheels) for offline testing
	@echo "$(DIM_GREEN)-> Building local wheels into wheelhouse/ via scripts/build_wheels.sh$(RESET)"
	@chmod +x scripts/build_wheels.sh
	@# Prepend venv PATH to access the operator's Python
	@env PATH="$(VENV_DIR)/bin:$$PATH" ./scripts/build_wheels.sh

# // ---[ Archives ]--- //

.PHONY: docs-serve
docs-serve: $(VENV_MARKER) ## 📜 Access the Architect's records (serve docs locally)
	@echo "$(DIM_GREEN)-> Accessing Architect's blueprints at http://127.0.0.1:8000$(RESET)"
	@$(PYTHON) -m mkdocs serve

.PHONY: docs-build
docs-build: $(VENV_MARKER) ## 📑 Compile the Architect's records (build docs)
	@echo "$(DIM_GREEN)-> Compiling documentation site...$(RESET)"
	@$(PYTHON) -m mkdocs build --clean

# // ---[ System Purge ]--- //

.PHONY: clean
clean: ## 🧹 Unplug from the Matrix (remove all generated files)
	@echo "$(DIM_GREEN)-> Erasing the Matrix... purging artifacts and caches...$(RESET)"
	@rm -rf $(VENV_DIR) $(BUILD_DIR) build *.egg-info
	@find . -type d -name "__pycache__" -exec rm -r {} +
	@find . -type d -name ".pytest_cache" -exec rm -r {} +
	@find . -type d -name ".mypy_cache" -exec rm -r {} +