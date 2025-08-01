# Matrix CLI

**Official command‑line interface for Matrix Hub** (Easily search, install, inspect agents/tools, and manage catalog remotes.)

---

## 🔧 Quick Start

### 1. Install

```bash
# Via pipx (recommended)
pipx install matrix-cli

# Or via pip
pip install matrix-cli
```
### 2. Configure
By default, Matrix CLI reads `~/.matrix/config.toml`.

You can bootstrap a minimal file:
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
ttl_seconds = 14400
```
You can also override per‑command:

```bash
matrix --base-url http://hub.example.com search "summarize pdfs"
```
Or via environment:

```bash
export MATRIX_BASE_URL=http://hub.example.com
export MATRIX_TOKEN=...
```

### 3. CLI Examples
**Health Check**
```bash
matrix show # shorthand for `matrix show`, fallback to help
matrix --version
matrix install --help
```
**Search**
```bash
matrix search "summarize pdfs" \
  --type agent \
  --capabilities pdf,summarize \
  --frameworks langgraph \
  --mode hybrid \
  --limit 10
```
**Show Details**
```bash
matrix show agent:pdf-summarizer@1.4.2 [--json]
```
Renders name, version, type, summary, capabilities, endpoints, artifacts, adapters.

**Install an Agent/Tool**
```bash
matrix install agent:pdf-summarizer@1.4.2 \
  --target ./apps/pdf-bot
```<id>` can be `type:name@version` or `type:name` with `--version`.
Writes adapters, registers with MCP-Gateway, and produces `matrix.lock.json`.

**List Registered Entities**
```bash
# From Matrix Hub index
matrix list --type tool --source hub

# From MCP‑Gateway
matrix list --type tool --source gateway
```
**Manage Catalog Remotes**
```bash
# List
matrix remotes list

# Add
matrix remotes add https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json \
    --name official

# Trigger Ingest
matrix remotes ingest official
```

## 📚 Documentation
Full user and developer docs powered by MkDocs are in the `docs/` folder.

Start a local preview:
```bash
pip install mkdocs mkdocs-material
mkdocs serve
```
Browse to `http://127.0.0.1:8000/`

## 🚀 Contributing
* Fork & clone.
* Create a feature branch: `git checkout -b feat/awesome`.
* Run tests: `pytest`.
* Lint & format: `ruff check .` & `black ..`.
* Submit a PR.

## 📄 License
Apache‑2.0 © agent‑matrix
