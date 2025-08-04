# Makefile for matrix-cli
# -----------------------------------------------------------------------------
# Variables (portable defaults)
# -----------------------------------------------------------------------------
# Try python3.11, then python3, then python
PY_BOOT      := $(shell command -v python3.11 >/dev/null 2>&1 && echo python3.11 || (command -v python3 >/dev/null 2>&1 && echo python3 || echo python))
VENV_DIR     := venv
BUILD_DIR    := dist
SRC_DIR      := matrix_cli
TEST_DIR     := tests
DOCS_DIR     := docs
CACHE_DIR    := ~/.cache/matrix

# Use .ONESHELL to ensure all commands in a recipe run in the same shell
.ONESHELL:

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  setup         Create a Python 3.11 virtual environment (falls back to python3/python)"
	@echo "  install       Install the package in editable mode with [ui,dev] extras"
	@echo "                (Run 'make setup' first, or ensure venv exists)"
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
	@echo "  uninstall     Uninstall matrix-cli and (optionally) local SDK"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean         Remove build artifacts, cache, and the virtual environment"
	@echo "  help          Show this message"

# -----------------------------------------------------------------------------
# Environment setup
# -----------------------------------------------------------------------------
setup:
	@echo "Creating Python virtual environment in $(VENV_DIR) using $(PY_BOOT)..."
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "Virtual environment already exists: $(VENV_DIR)"; \
	else \
		$(PY_BOOT) -m venv $(VENV_DIR); \
	fi
	@echo ""
	@echo "Activate it with:"
	@echo "  source $(VENV_DIR)/bin/activate   # Linux/macOS"
	@echo "  .\\$(VENV_DIR)\\Scripts\\activate  # Windows (CMD/PowerShell)"

install: setup
	@echo "Installing matrix-cli (editable) with [ui,dev] extras..."
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m pip install --upgrade pip setuptools wheel
	if [ -d "../matrix-python-sdk" ]; then \
		echo "Installing local SDK from ../matrix-python-sdk (editable)..."; \
		python -m pip install -e ../matrix-python-sdk; \
	fi
	python -m pip install -e ".[ui,dev]"

# -----------------------------------------------------------------------------
# Linting & Formatting
# -----------------------------------------------------------------------------
lint: install
	@echo "Running linter (ruff + flake8)…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m ruff check $(SRC_DIR) $(TEST_DIR)
	python -m flake8 $(SRC_DIR) $(TEST_DIR)

fmt: install
	@echo "Formatting code with black…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m black $(SRC_DIR) pyproject.toml mkdocs.yml

typecheck: install
	@echo "Running mypy…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m mypy $(SRC_DIR)

# -----------------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------------
test: install
	@echo "Running pytest…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m pytest -q --disable-warnings --maxfail=1

# -----------------------------------------------------------------------------
# Build & Publish
# -----------------------------------------------------------------------------
build: install
	@echo "Building source distribution and wheel…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m build

publish: build
	@echo "Publishing to PyPI via twine…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m twine upload $(BUILD_DIR)/*

# -----------------------------------------------------------------------------
# Documentation (MkDocs)
# -----------------------------------------------------------------------------
docs-serve: install
	@echo "Launching MkDocs dev server…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m mkdocs serve

docs-build: install
	@echo "Building MkDocs static site…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m mkdocs build --clean

docs-clean:
	@echo "Cleaning MkDocs site/ directory…"
	rm -rf site/

# -----------------------------------------------------------------------------
# UI Launcher & Uninstall
# -----------------------------------------------------------------------------
ui: install
	@echo "Launching Matrix UI shell..."
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	matrix

uninstall:
	@echo "Uninstalling matrix-cli (and local SDK if installed)…"
	. $(VENV_DIR)/bin/activate 2>/dev/null || . $(VENV_DIR)/Scripts/activate
	python -m pip uninstall -y matrix-cli || true
	if python -c "import pkgutil,sys; sys.exit(0 if pkgutil.find_loader('matrix_sdk') else 1)"; then \
		python -m pip uninstall -y matrix-python-sdk || true; \
	fi

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
clean:
	@echo "Removing build artifacts, caches, and virtual environment…"
	rm -rf $(BUILD_DIR) *.egg-info
	rm -rf site/
	rm -rf $(CACHE_DIR)
	rm -rf $(VENV_DIR)
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -exec rm -rf {} +

# -----------------------------------------------------------------------------
# Phony targets
# -----------------------------------------------------------------------------
.PHONY: help setup install lint fmt typecheck test build publish docs-serve docs-build docs-clean ui uninstall clean