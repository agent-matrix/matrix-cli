# ====================================================================================
# Makefile for the Matrix CLI Project
#
# This Makefile automates common development tasks such as installation, linting,
# testing, building, and publishing. It is designed to be self-documenting.
# Run `make help` to see all available commands.
# ====================================================================================

# --- Shell and Environment Setup ---
# Use a single shell for each recipe, allowing `cd` and `source` to persist.
.ONESHELL:
# The default target that runs when `make` is called without arguments.
.DEFAULT_GOAL := help

# --- Variables ---
# Python discovery (prefer python3.11, fallback to python3, then python)
PY_BOOT       := $(shell command -v python3.11 || command -v python3 || command -v python)
VENV_DIR      := .venv
PYTHON        := $(VENV_DIR)/bin/python
VENV_MARKER   := $(VENV_DIR)/.installed
SRC_DIR       := matrix_cli
TEST_DIR      := tests
BUILD_DIR     := dist

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
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

.PHONY: setup
setup: .venv/pyvenv.cfg ## 🛠️  Create a virtual environment in .venv

# This is a file-based prerequisite. It will only run if the file doesn't exist.
.venv/pyvenv.cfg:
	@echo "-> Creating virtual environment in $(VENV_DIR) using $(PY_BOOT)..."
	@$(PY_BOOT) -m venv $(VENV_DIR)

# This target installs dependencies and creates a marker file.
# It only runs if the marker is missing or if pyproject.toml has changed.
$(VENV_MARKER): .venv/pyvenv.cfg pyproject.toml
	@echo "-> Installing/updating dependencies from pyproject.toml..."
	@$(PYTHON) -m pip install -q --upgrade pip
	@$(PYTHON) -m pip install -e ".[dev]"
	@touch $@

# The `install` target will now always run its recipe to force a reinstall.
# NOTE: The command lines below MUST be indented with a single TAB character, not spaces.
.PHONY: install
install: $(VENV_MARKER) ## 📦 Force re-install of the local package to reflect code changes
	@echo "-> Forcing re-installation of local package..."
	# --force-reinstall: Reinstalls the package even if it's already installed.
	# --no-deps: Avoids re-installing all third-party dependencies, making it much faster.
	@$(PYTHON) -m pip install --force-reinstall --no-deps -e ".[dev]"

# --- Quality Assurance ---

.PHONY: fmt
fmt: $(VENV_MARKER) ## 🎨 Format code with Black and Ruff
	@echo "-> Formatting code..."
	@$(PYTHON) -m black $(SRC_DIR) $(TEST_DIR) pyproject.toml
	@$(PYTHON) -m ruff format $(SRC_DIR) $(TEST_DIR) pyproject.toml

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

.PHONY: test
test: $(VENV_MARKER) ## 🧪 Run tests with Pytest
	@echo "-> Running tests..."
	@$(PYTHON) -m pytest --maxfail=1

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

.PHONY: uninstall
uninstall: ## 🗑️  Uninstall the project and its core dependencies
	@echo "-> Uninstalling packages..."
	@if [ -f "$(PYTHON)" ]; then $(PYTHON) -m pip uninstall -y matrix-cli matrix-python-sdk || true; fi

.PHONY: clean
clean: ## 🧹 Remove build artifacts, caches, and the virtual environment
	@echo "-> Cleaning up project files..."
	@rm -rf $(BUILD_DIR) build *.egg-info .pytest_cache .mypy_cache .ruff_cache site/ coverage.xml
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@if [ -d "$(VENV_DIR)" ]; then rm -rf $(VENV_DIR); fi