# Matrix CLI

Official command-line interface for **Matrix Hub** — search, inspect, install, run, probe MCP servers, manage remotes, check connectivity, and safely uninstall.

> Requires **Python 3.11+** and the **matrix-python-sdk ≥ 0.1.5**.

---

## 🚀 What’s new in v0.1.2

* **`matrix connection`** — quick Hub health check
  Human output or `--json` (exit code **0** healthy, **2** unhealthy).
* **`matrix mcp`** — probe/call local MCP servers (SSE/WebSocket)
  `matrix mcp probe --alias <name>` auto-discovers the port; or pass `--url`.
* **Safer installs** — no local absolute paths sent to the Hub
  The CLI sends `<alias>/<version>` to the Hub and materializes locally.
* **`matrix ps` shows URL** and now supports **`--plain`** and **`--json`** for scripting.
* **`matrix uninstall`** — safe, scriptable uninstaller for one/many aliases, with optional `--purge` of files.
* **TLS hardening** — consistent certificate verification (env CA/OS trust/certifi).

---

## 📦 Install

```bash
# Recommended
pipx install matrix-cli

# Or with pip (active virtualenv)
pip install matrix-cli
```

### Optional extras

```bash
# Add MCP client (SSE works; WebSocket needs `websockets`)
pip install "matrix-cli[mcp]"   # installs mcp>=1.13.1

# If you want WebSocket probing too:
pip install websockets

# Dev extras (linting, tests, docs)
pip install "matrix-cli[dev]"

# Using pipx? You can inject extras later:
pipx inject matrix-cli mcp websockets
```

---

## ⚙️ Configuration

The CLI reads, in order: **environment variables**, `~/.config/matrix/cli.toml` (optional), then built-ins.

### Environment

```bash
export MATRIX_HUB_BASE="https://api.matrixhub.io"   # or your dev hub
export MATRIX_HUB_TOKEN="..."                       # optional
export MATRIX_HOME="$HOME/.matrix"                  # optional; default ~/.matrix

# TLS (corporate CA/proxy)
export SSL_CERT_FILE=/path/to/ca.pem
# or
export REQUESTS_CA_BUNDLE=/path/to/ca.pem

# ps URL host override (display only)
export MATRIX_PS_HOST="localhost"
```

### Optional TOML (`~/.config/matrix/cli.toml`)

```toml
hub_base = "https://api.matrixhub.io"
token    = ""
home     = "~/.matrix"
```

---

## 🏁 Quick start

```bash
# Basics
matrix --version
matrix help
matrix version

# Search (includes pending by default)
matrix search "hello"

# Filtered search
matrix search "hello" --type mcp_server --limit 5

# Install (short name resolves to mcp_server:<name>@<latest>)
matrix install hello-sse-server --alias hello-sse-server

# Run and inspect
matrix run hello-sse-server
matrix ps                                # shows URL column
matrix logs hello-sse-server -f
matrix stop hello-sse-server

# Show raw details
matrix show mcp_server:hello-sse-server@0.1.0

# Hub health (human / JSON for CI)
matrix connection
matrix connection --json --timeout 3.0
```

## Matrix CLI Demo

![Matrix CLI Demo](assets/matrix-cli-demo.gif)

---

## 🔍 Search tips

Useful filters:

* `--type {agent|tool|mcp_server}`
* `--mode {keyword|semantic|hybrid}`
* `--capabilities rag,sql`
* `--frameworks langchain,autogen`
* `--providers openai,anthropic`
* `--with-snippets`
* `--certified` (registered/certified only)
* `--json` for programmatic output
* `--exact` to fetch a specific ID

Examples:

```bash
# MCP servers about "hello"
matrix search "hello" --type mcp_server --limit 5

# Hybrid mode with snippets
matrix search "vector" --mode hybrid --with-snippets

# Structured results
matrix search "sql agent" --capabilities rag,sql --json
```

> If the public Hub is unreachable, some operations try a **local dev Hub** once and tell you.

---

## 🧩 Install behavior (safer by design)

* Accepts `name`, `name@ver`, `ns:name`, `ns:name@ver`
* If `ns` missing, prefers **`mcp_server`**
* If `@version` missing, picks **latest** (stable > pre-release)
* Uses a small cache under `~/.matrix/cache/resolve.json` (per-hub, short TTL)
* **No absolute paths sent to the Hub** — the CLI sends a safe `<alias>/<version>` label, then **materializes locally**
* Preflight checks ensure your local target is **writable** before network calls

Examples:

```bash
# Short name; alias is optional (auto-suggested if omitted)
matrix install hello-sse-server --alias hello-sse-server

# Specific version
matrix install mcp_server:hello-sse-server@0.1.0

# Custom target
matrix install hello-sse-server --target ~/.matrix/runners/hello-sse-server/0.1.0
```

---

## ▶️ Run UX (with handy next steps)

`matrix run <alias>` prints a click-ready **URL** and **Health** link, plus a logs hint.
Typical follow-ups you can run immediately:

```bash
# Probe tools exposed by your local MCP server (auto-discovers port)
matrix mcp probe --alias hello-sse-server

# Call a tool (optional args as JSON)
matrix mcp call hello --alias hello-sse-server --args '{}'
```

---

## 🧪 MCP utilities (SSE/WS)

Probe and call tools on local MCP servers.

```bash
# Probe by alias (auto-discovers port; infers endpoint from runner.json or uses /messages/)
matrix mcp probe --alias hello-sse-server

# Or probe by full SSE URL
matrix mcp probe --url http://127.0.0.1:52305/messages/

# Call a tool (optional args as JSON)
matrix mcp call hello --alias hello-sse-server --args '{}'

# JSON mode for scripts
matrix mcp probe --alias hello-sse-server --json
```

Notes:

* SSE works with `mcp>=1.13.1` (installed via the `mcp` extra).
* WebSocket URLs (`ws://`/`wss://`) require the `websockets` package.
* For non-running aliases, you’ll get helpful suggestions based on `matrix ps`.

---

## 🧭 Process management

`matrix ps` shows a **URL** column constructed from the runner’s port and endpoint
(auto-read from `runner.json` where possible, default `/messages/`):

```
┏━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ALIAS            ┃  PID ┃  PORT ┃ UPTIME   ┃ URL                              ┃ TARGET                           ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ hello-sse-server │ 1234 ┃ 52305 ┃ 02:18:44 │ http://127.0.0.1:52305/messages/ │ ~/.matrix/runners/hello…/0.1.0   │
└──────────────────┴──────┴───────┴──────────┴──────────────────────────────────┴──────────────────────────────────┘
```

Copy the URL directly into:

```bash
matrix mcp probe --url http://127.0.0.1:52305/messages/
```

Script-friendly output:

```bash
# Plain (space-delimited): alias pid port uptime_seconds url target
matrix ps --plain

# JSON: array of objects with {alias,pid,port,uptime_seconds,url,target}
matrix ps --json
```

Other commands:

```bash
matrix logs <alias> [-f]
matrix stop <alias>
matrix doctor <alias>
```

---

## 🌐 Hub health & TLS

```bash
# Quick Hub health
matrix connection
matrix connection --json
```

TLS policy:

* Respects `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE`
* Tries OS trust (when available)
* Falls back to `certifi`
* Never throws on network errors in health checks — returns a structured status with exit codes.

---

## 🧹 Safe uninstall

Remove one or many aliases, and optionally purge local files.

```bash
# Uninstall one alias (keeps files by default)
matrix uninstall hello-sse-server

# Uninstall several and also delete files (safe paths only)
matrix uninstall hello-a hello-b --purge

# Remove everything from the local alias store (stop first, purge files)
matrix uninstall --all --force-stop --purge -y

# Dry-run (show what would be removed)
matrix uninstall --all --dry-run
```

Safety features:

* Only purges targets under `~/.matrix/runners` by default.
* Skips deleting files still referenced by other aliases.
* `--force-files` allows deleting outside the safe path (⚠️ DANGEROUS; off by default).
* `--stopped-only` to avoid touching running aliases.

Exit codes: **0** success, **2** partial/failed.

---

## 🧰 Scripting & CI examples

```bash
# Search, parse with jq, then install the first result
results=$(matrix search "ocr table" --type tool --json)
first_id=$(echo "$results" | jq -r '.items[0].id')
matrix install "$first_id" --alias ocr-table --force --no-prompt

# Health check in CI (exit code 0/2)
matrix connection --json

# Get the port quickly for an alias
port=$(matrix ps --plain | awk '$1=="hello-sse-server"{print $3; exit}')
matrix mcp probe --url "http://127.0.0.1:${port}/messages/" --json
```

---

## 🐞 Troubleshooting

* **“Missing 'mcp' package”**
  Install the optional extra: `pip install "matrix-cli[mcp]"`
  (For WebSocket endpoints also: `pip install websockets`.)

* **TLS / certificate errors**
  Set `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` to your CA bundle:

  ```bash
  export SSL_CERT_FILE=/path/to/ca.pem
  # or
  export REQUESTS_CA_BUNDLE=/path/to/ca.pem
  ```

* **Alias not found when probing**
  Use the alias shown by `matrix ps` (case-insensitive match supported), or pass `--url` directly.

---

## 🛠️ Development

```bash
# Create venv and install (editable) with useful extras
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[ui,dev,mcp]"

# Common tasks (Makefile may vary by repo)
make lint       # ruff/flake8
make fmt        # black
make typecheck  # mypy
make test       # pytest
make build      # sdist + wheel
```

---

## 📄 License

Apache License 2.0

---

## ✉️ Feedback

Issues and PRs welcome! If you hit rough edges with install/probing/health or the new `ps --plain/--json` and `uninstall` flows, please open an issue including your command, output, and environment details.
