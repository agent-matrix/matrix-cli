
# Matrix CLI

**Official command-line interface for Matrix Hub**
Search, inspect, install, and run agents/tools — plus manage remote catalogs.

---

## ✨ What’s in this version (0.1.1)

* **Fast, reliable search**

  * Pending results **included by default** so you actually find things.
  * `--certified` to filter to registered/certified only.
  * `--json` for raw payloads, `--exact` to fetch a specific ID, `--show-status` to print `(pending)`/`(certified)`.
  * If the public hub can’t be reached, the CLI **tries your local dev hub once** and tells you.

* **Smarter installs (one call in the common case)**

  * Install by short name: `matrix install hello-sse-server` → resolves to `mcp_server:hello-sse-server@<latest>`.
  * If `@version` is omitted, the resolver picks **latest** (prefers stable > pre-release).
  * Prefers **`mcp_server`** when no namespace is given.
  * Uses a tiny on-disk cache (`~/.matrix/cache/resolve.json`, \~5 min TTL) to avoid repeat lookups.
  * If the public hub can’t be reached, build **falls back to local dev hub** once.

* **Better “run” UX**

  * After start, prints a **clickable URL** and **health URL** alongside the logs hint.

* **Process management**

  * `ps`, `logs`, `stop`, and `doctor` to manage and verify local processes.

* **Remotes management**

  * `remotes list|add|ingest|remove` to manage remote catalogs.

> Requires **Python 3.11+** and **matrix-python-sdk ≥ 0.1.2**.

---

## 🔧 Install

```bash
# Via pipx (recommended)
pipx install matrix-cli

# Or via pip
pip install matrix-cli
```

---

## ⚙️ Configuration

Matrix CLI reads (in order of precedence):

1. **Environment variables**
2. Optional **TOML** at `~/.config/matrix/cli.toml`
3. Built-in defaults

### Environment variables

```bash
export MATRIX_HUB_BASE=https://api.matrixhub.io   # or http://localhost:7300
export MATRIX_HUB_TOKEN=...                       # optional
export MATRIX_HOME=~/.matrix                      # optional; default is ~/.matrix
```

### Optional TOML (`~/.config/matrix/cli.toml`)

```toml
hub_base = "https://api.matrixhub.io"  # or "http://localhost:7300"
token = ""                             # optional
home = "~/.matrix"                     # optional
```

---

## 🚀 Quick start

```bash
# Version / help
matrix --version
matrix --help
matrix version

# Search (includes pending by default)
matrix search "hello"

# Certified-only search
matrix search "hello" --certified

# Programmatic JSON results
matrix search "hello" --json --limit 10

# Exact entity by ID
matrix search "mcp_server:hello-sse-server@0.1.0" --exact

# Install by short name (picks latest, prefers mcp_server)
matrix install hello-sse-server

# Or install specific version / fully qualified
matrix install mcp_server:hello-sse-server@0.1.0

# Run & open
matrix run hello-sse-server
# (prints: Open in browser / Health / logs hint)

# Show details (pretty-prints JSON by default)
matrix show mcp_server:hello-sse-server@0.1.0

# Manage processes
matrix ps
matrix logs hello-sse-server -f
matrix stop hello-sse-server
matrix doctor hello-sse-server

# Remotes (catalogs)
matrix remotes list
matrix remotes add https://example.com/catalog.json --name example
matrix remotes ingest example
matrix remotes remove example
```

---

## 🔍 Search tips

* Pending results are **included by default** for better coverage. Use `--certified` for registered-only.
* Useful filters:

  * `--type {agent|tool|mcp_server}`
  * `--mode {keyword|semantic|hybrid}`
  * `--capabilities rag,sql`
  * `--frameworks langchain,autogen`
  * `--providers openai,anthropic`
  * `--with-snippets`

Examples:

```bash
# mcp servers about hello
matrix search "hello" --type mcp_server --limit 5

# Hybrid mode, with snippets
matrix search "vector" --mode hybrid --with-snippets

# Programmatic consumption
matrix search "sql agent" --capabilities rag,sql --json
```

If the public hub is unreachable, the CLI will try your local dev hub at `http://localhost:7300` once and let you know.

---

## 🧠 Install resolver behavior

* Accepts: `name`, `name@1.2.3`, `ns:name`, `ns:name@1.2.3`.
* If `ns` is missing, **prefers `mcp_server`** candidates.
* If `@version` is missing, picks **latest** (stable > pre-release, then highest).
* Uses a tiny, short-lived cache under `~/.matrix/cache/resolve.json` per hub.
* On DNS/connection failures to the public hub, tries `http://localhost:7300` once.

---

## 🩺 Health & processes

```bash
# Start a server by alias
matrix run my-alias
# → prints: PID, Port, Open in browser, Health URL, and logs hint

# Check health of a running alias
matrix doctor my-alias
```

---

## 🛠️ Remotes

```bash
matrix remotes list
matrix remotes add https://raw.githubusercontent.com/your-org/catalog/main/index.json --name official
matrix remotes ingest official
matrix remotes remove official
```

---

## ❓ Troubleshooting

* **No results?** Try `--certified` (if you only want registered) or omit it to include pending.
  If your catalog isn’t ingested yet:
  `matrix remotes ingest <remote-name>`
* **Offline?** The CLI will attempt a one-time fallback to `http://localhost:7300` where applicable.
* **Install by name fails?** Try a more specific query in `matrix search`, then install using the fully qualified ID.

---

## 📄 License

Apache License 2.0 © ruslanmv.com

