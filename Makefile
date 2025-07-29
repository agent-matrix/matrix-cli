# Makefile for matrix-cli
# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------
# Use python3.11 to create the venv, as required by pyproject.toml
PYTHON_VERSION := python3.11
VENV_DIR       := venv
PYTHON         := $(VENV_DIR)/bin/python3
PIP            := $(PYTHON) -m pip
BUILD_DIR      := dist
SRC_DIR        := matrix_cli
TEST_DIR       := tests
DOCS_DIR       := docs
MKDOCS         := $(VENV_DIR)/bin/mkdocs
CACHE_DIR      := ~/.cache/matrix

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  setup         Create a Python 3.11 virtual environment"
	@echo "  install       Install the package and dependencies into the virtual environment"
	@echo "                (Run 'make setup' and activate the venv first)"
	@echo ""
	@echo "Development:"
	@echo "  lint          Run ruff + flake8"
	@echo "  fmt           Run black"
	@echo "  typecheck     Run mypy"
	@echo "  test          Run pytest"
	@echo ""
	@echo "Build & Publish:"
	@echo "  build         Build sdist & wheel"
	@echo "  publish       Upload to PyPI via twine"
	@echo ""
	@echo "Docs targets:"
	@echo "  docs-serve    Serve MkDocs site at http://127.0.0.1:8000"
	@echo "  docs-build    Build MkDocs static site into site/"
	@echo "  docs-clean    Remove built site/ directory"
	@echo ""
	@echo "Terminal:"
	@echo "  ui            Launch the Matrix UI shell"
	@echo "  uninstall     Uninstall matrix-cli and extras"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean         Remove build artifacts, cache, and the virtual environment"
	@echo "  help          Show this message"

# -----------------------------------------------------------------------------
# Environment setup
# -----------------------------------------------------------------------------
setup:
	@echo "Creating Python virtual environment in $(VENV_DIR) using $(PYTHON_VERSION)..."
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "Virtual environment already exists."; \
	else \
		$(PYTHON_VERSION) -m venv $(VENV_DIR); \
	fi
	@echo ""
	@echo "Environment created. Activate it by running:"
	@echo "source $(VENV_DIR)/bin/activate"

install:
	@echo "Installing local SDK and matrix-cli with UI extras in editable mode..."
	# Ensure pip is up-to-date within the venv
	$(PIP) install --upgrade pip
	# Install the local SDK dependency first
	$(PIP) install -e ../matrix-python-sdk
	# Install the matrix-cli package itself in editable mode, with the [ui] extras.
	# This automatically installs all other dependencies from pyproject.toml.
	$(PIP) install -e '.[ui]'

# -----------------------------------------------------------------------------
# Linting & Formatting
# -----------------------------------------------------------------------------
lint:
	@echo "Running linter (ruff + flake8)…"
	$(VENV_DIR)/bin/ruff check $(SRC_DIR) $(TEST_DIR)
	$(VENV_DIR)/bin/flake8 $(SRC_DIR) $(TEST_DIR)

fmt:
	@echo "Formatting code with black…"
	$(VENV_DIR)/bin/black $(SRC_DIR) pyproject.toml mkdocs.yml

typecheck:
	@echo "Running mypy…"
	$(VENV_DIR)/bin/mypy $(SRC_DIR)

# -----------------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------------
test:
	@echo "Running pytest…"
	$(VENV_DIR)/bin/pytest -q --disable-warnings --maxfail=1

# -----------------------------------------------------------------------------
# Build & Publish
# -----------------------------------------------------------------------------
build:
	@echo "Building source & wheel…"
	$(PYTHON) -m build --sdist --wheel

publish: build
	@echo "Publishing to PyPI…"
	$(VENV_DIR)/bin/twine upload $(BUILD_DIR)/*

# -----------------------------------------------------------------------------
# Documentation (MkDocs)
# -----------------------------------------------------------------------------
docs-serve:
	@echo "Launching MkDocs dev server…"
	$(MKDOCS) serve

docs-build:
	@echo "Building MkDocs static site…"
	$(MKDOCS) build

docs-clean:
	@echo "Cleaning MkDocs site/ directory…"
	rm -rf site/

# -----------------------------------------------------------------------------
# UI Launcher & Uninstall
# -----------------------------------------------------------------------------
ui:
	@echo "Launching Matrix UI shell..."
	$(VENV_DIR)/bin/matrix-ui

uninstall:
	@echo "Uninstalling matrix-cli and optional UI extras..."
	$(PIP) uninstall -y matrix-cli matrix-python-sdk

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
clean:
	@echo "Removing build artifacts, cache, and virtual environment…"
	rm -rf $(BUILD_DIR) *.egg-info
	rm -rf site/
	rm -rf $(CACHE_DIR)
	rm -rf $(VENV_DIR)
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} +

# -----------------------------------------------------------------------------
# Phony targets
# -----------------------------------------------------------------------------
.PHONY: help setup install lint fmt typecheck test build publish docs-serve docs-build docs-clean ui uninstall clean
