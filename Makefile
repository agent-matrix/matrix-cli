# ====================================================================================
# Makefile for the Matrix CLI Project
#
# This Makefile automates common development tasks such as installation, linting,
# testing, building, and publishing. It is designed to be self-documenting.
# Run `make help` to see all available commands.
# ====================================================================================

# --- Shell and Environment Setup ---
.ONESHELL:
.DEFAULT_GOAL := help

# --- Variables ---
PY_BOOT       := $(shell command -v python3.11 || command -v python3 || command -v python)
VENV_DIR      := .venv
PYTHON        := $(VENV_DIR)/bin/python
VENV_MARKER   := $(VENV_DIR)/.installed
SRC_DIR       := matrix_cli
TEST_DIR      := tests
BUILD_DIR     := dist

# Which extras to install from pyproject.toml:
#   dev  = full toolchain (tests, lint, format, typecheck, build, publish, docs)
#   test = only the test tools (pytest, pytest-cov, pytest-mock)
EXTRAS        ?= dev

# Terminal colors for help text
GREEN         := $(shell tput -T screen setaf 2)
YELLOW        := $(shell tput -T screen setaf 3)
CYAN          := $(shell tput -T screen setaf 6)
RESET         := $(shell tput -T screen sgr0)

# --- Core Targets ---

.PHONY: help
help: ## ✨ Show this help message
	@echo
	@echo "Usage: make <target>"
	@echo
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "    $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

.PHONY: setup
setup: .venv/pyvenv.cfg ## 🛠️  Create a virtual environment in .venv

.venv/pyvenv.cfg:
	@echo "-> Creating virtual environment in $(VENV_DIR) using $(PY_BOOT)..."
	@$(PY_BOOT) -m venv $(VENV_DIR)

# Install deps once (or when pyproject.toml changes)
$(VENV_MARKER): .venv/pyvenv.cfg pyproject.toml
	@echo "-> Installing/updating dependencies from pyproject.toml (extras: $(EXTRAS))..."
	@$(PYTHON) -m pip install -q --upgrade pip setuptools wheel
	@$(PYTHON) -m pip install -e ".[$(EXTRAS)]"
	@touch $@

.PHONY: install
install: $(VENV_MARKER) ## 📦 Force re-install of the local package to reflect code changes
	@echo "-> Forcing re-installation of local package (extras: $(EXTRAS))..."
	@$(PYTHON) -m pip install --force-reinstall --no-deps -e ".[$(EXTRAS)]"

# Convenience: install only test tools (pytest, pytest-cov, pytest-mock)
.PHONY: install-test-tools
install-test-tools: .venv/pyvenv.cfg ## 🧪 Install only test tools (pytest, pytest-cov, pytest-mock)
	@echo "-> Installing test extras..."
	@$(PYTHON) -m pip install -q --upgrade pip setuptools wheel
	@$(PYTHON) -m pip install -e ".[test]"

# --- Quality Assurance ---

.PHONY: fmt
fmt: $(VENV_MARKER) ## 🎨 Format code with Black and Ruff
	@echo "-> Formatting code..."
	@$(PYTHON) -m black $(SRC_DIR) $(TEST_DIR)
	@$(PYTHON) -m ruff format $(SRC_DIR) $(TEST_DIR)

.PHONY: lint
lint: $(VENV_MARKER) ## 🧹 Lint code with Ruff and Flake8
	@echo "-> Linting code..."
	@$(PYTHON) -m ruff check $(SRC_DIR) $(TEST_DIR)
	@$(PYTHON) -m flake8 $(SRC_DIR) $(TEST_DIR)

.PHONY: typecheck
typecheck: $(VENV_MARKER) ## 🧐 Run Mypy for static type checking
	@echo "-> Running type checks..."
	@$(PYTHON) -m mypy $(SRC_DIR)

.PHONY: qa
qa: fmt lint typecheck ## 💯 Run all quality assurance checks (format, lint, typecheck)

# --- Testing ---

# IMPORTANT: Do not depend on $(VENV_MARKER) so running tests won't reinstall anything.
.PHONY: test
test: .venv/pyvenv.cfg ## 🧪 Run tests with Pytest (no re-install)
	@echo "-> Running tests..."
	@if [ ! -x "$(VENV_DIR)/bin/pytest" ]; then \
		echo "!! pytest not found in $(VENV_DIR). Run 'make install-test-tools' or 'make install' first."; \
		exit 1; \
	fi
	@$(VENV_DIR)/bin/pytest --maxfail=1

# --- Build & Release ---

.PHONY: build
build: $(VENV_MARKER) ## 🏗️  Build sdist and wheel packages
	@echo "-> Building distribution packages..."
	@rm -rf $(BUILD_DIR) build
	@$(PYTHON) -m build

.PHONY: publish
publish: build ## 🚀 Upload packages to PyPI using Twine
	@echo "-> Publishing to PyPI..."
	@$(PYTHON) -m twine upload $(BUILD_DIR)/*

# --- Documentation ---

.PHONY: docs-serve
docs-serve: $(VENV_MARKER) ## 📖 Serve documentation locally with MkDocs
	@echo "-> Serving docs at http://127.0.0.1:8000"
	@$(PYTHON) -m mkdocs serve

.PHONY: docs-build
docs-build: $(VENV_MARKER) ## 📑 Build the documentation site
	@echo "-> Building documentation site..."
	@$(PYTHON) -m mkdocs build --clean

# --- Maintenance ---

.PHONY: clean
clean: ## 🧹 Remove virtual environment, build artifacts, and caches
	@echo "-> Cleaning up project..."
	@rm -rf $(VENV_DIR) $(BUILD_DIR) build *.egg-info
	@find . -type d -name "__pycache__" -exec rm -r {} +
	@find . -type d -name ".pytest_cache" -exec rm -r {} +
	@find . -type d -name ".mypy_cache" -exec rm -r {} +