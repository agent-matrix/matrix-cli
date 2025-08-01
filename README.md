![](assets/2025-08-01-18-44-48.png)

# Matrix CLI

**Official command-line interface for Matrix Hub**  
Search, inspect, install agents/tools, and manage catalog remotes — plus an interactive **Matrix Shell** REPL.

---

## ✨ Features

- **Interactive Matrix Shell (REPL)** with history, completions, and built-in commands.
- **Options at the group level**: `--version`, `--rain/--no-rain`, `--no-repl`.
- **Session-wide rain toggle**: turn the Matrix rain on/off at startup or dynamically inside the REPL.
- **Polished UX**:
  - `help` does **not** clear the screen.
  - `matrix exit`, `exit`, `quit`, `close` all exit cleanly.
  - Typing a redundant `matrix` token in the REPL is accepted.
  - Robust autocompletion even when options are typed first (e.g., `--no-rain`).

---

## 🔧 Installation

```bash
# Via pipx (recommended)
pipx install matrix-cli

# Or via pip
pip install matrix-cli
```

> **Requires** Python 3.11+.

---

## ⚙️ Configuration

By default, Matrix CLI reads `~/.matrix/config.toml`.

Create a minimal config:

```toml
# ~/.matrix/config.toml

[registry]
base_url = "http://localhost:7300"
token = "YOUR_MATRIX_TOKEN"      # optional

[gateway]
base_url = "http://localhost:7200"
token = "YOUR_GATEWAY_TOKEN"     # optional

[cache]
dir = "~/.cache/matrix"
ttl_seconds = 14400              # 4 hours
```

You can override per command:

```bash
matrix --base-url http://hub.example.com search "summarize pdfs"
```

Or via environment variables:

```bash
export MATRIX_BASE_URL=http://hub.example.com
export MATRIX_TOKEN=...
export MATRIX_EXTRA_CATALOGS="https://example.com/cat1.json,https://example.com/cat2.json"

export MCP_GATEWAY_URL=http://gateway.example.com
export MCP_GATEWAY_TOKEN=...

export MATRIX_CACHE_DIR=~/.cache/matrix
export MATRIX_CACHE_TTL=14400
```

---

## 🚀 Quick Start

### One-shot (non-interactive) usage

```bash
# Version
matrix --version

# Show help for top level
matrix --help

# Disable REPL after running a command
matrix --no-repl --help
```

### Interactive Matrix Shell (REPL)

Just run:

```bash
matrix
```

Inside the shell:

* `help` or `matrix help` → show commands and usage (no screen clear).
* `help <command>` → detailed help for a specific command.
* `clear` or `matrix clear` → clear the screen.
* `--no-rain` / `--rain` → toggle Matrix rain **for the current session**.
* `exit`, `quit`, `close`, or `matrix exit` → exit the shell.

You can also pass options on entry:

```bash
# Start without the rain animation
matrix --no-rain

# Print help then exit (do not enter REPL)
matrix --no-repl --help
```

> The REPL accepts a redundant leading `matrix` token, so `matrix help`, `matrix exit`, etc. work as expected.

---

## 🧭 Common Commands

### Health / Info

```bash
matrix --version
matrix --help
```

### Search

```bash
matrix search "summarize pdfs" \
  --type agent \
  --capabilities pdf,summarize \
  --frameworks langgraph \
  --mode hybrid \
  --limit 10
```

### Show Details

```bash
# id can be type:name@version or type:name with --version
matrix show agent:pdf-summarizer@1.4.2 [--json]
```

Renders name, version, type, summary, capabilities, endpoints, artifacts, adapters.

### Install

```bash
matrix install agent:pdf-summarizer@1.4.2 \
  --target ./apps/pdf-bot
```

Writes adapters, registers with MCP-Gateway, and produces `matrix.lock.json`.

### List Entities

```bash
# From Matrix Hub index
matrix list --type tool --source hub

# From MCP-Gateway
matrix list --type tool --source gateway
```

### Manage Catalog Remotes

```bash
# List
matrix remotes list

# Add
matrix remotes add https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json \
  --name official

# Trigger ingest
matrix remotes ingest official
```

---

## 🧩 Options (Top-Level Group)

These options apply both at startup and **inside** the REPL:

* `--version`
  Print the installed `matrix-cli` version and exit.
* `--rain / --no-rain`
  Enable/disable the Matrix rain animation. Inside the REPL this toggles the session state.
* `--no-repl`
  Run the requested action (e.g., `--help`) and exit **without** entering the REPL.
* `--help`
  Show top-level help.

---

## 💡 Tips & Troubleshooting

* If you type `matrix --no-rain` **inside** the REPL, the animation toggles for the rest of the session; the shell does **not** restart or clear your screen.
* `help` in the REPL never clears the screen (use `clear` if you want a fresh view).
* Autocompletion is resilient even when you start with options (e.g., `--no-rain` first).
* If you installed with `pipx`, ensure your shell is picking up the `pipx` bin path.

---

## 📚 Documentation

Full user and developer docs live in the `docs/` folder.

Preview locally:

```bash
pip install mkdocs mkdocs-material
mkdocs serve
```

Open `http://127.0.0.1:8000/`.

---

## 🛠️ Development

```bash
# clone & setup venv
git clone https://github.com/agent-matrix/matrix-cli.git
cd matrix-cli
python -m venv .venv && source .venv/bin/activate

# install dev deps
pip install -e ".[dev]"

# lint & format
ruff check .
black .

# run tests
pytest
```

---

## 📄 License

Apache-2.0 © agent-matrix

