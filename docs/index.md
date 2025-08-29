<!-- docs/index.md -->

# Matrix CLI (v0.1.3)

> **MatrixHub** is building the *pip of agents & MCP servers* — search, install, run, and connect.
>
> The **Matrix CLI** is a thin, fast UX over the Matrix Python SDK. It works with public and private Matrix Hubs.

## Why MatrixHub?

* **Discoverability** — Search a global catalog of agents, tools, and MCP servers.
* **One‑line installs** — Clean install plans; local materialization stays on your machine.
* **Runtime built‑in** — Start/stop processes, tail logs, and health‑check.
* **MCP‑native** — Probe and call tools over SSE/WS with zero boilerplate.
* **Enterprise‑grade TLS** — Honors corporate CAs via `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`.

## CLI highlights

* `matrix search` — rich filters, JSON output for scripting
* `matrix install` — safe planning; no absolute paths sent to the Hub
* `matrix run`, `matrix ps`, `matrix logs`, `matrix stop`
* `matrix mcp probe` / `matrix mcp call` — attach to **local** or **remote** MCP
* `matrix connection` — Hub health (human + JSON)
* `matrix uninstall` — safe, scriptable removal

---

## Example (end‑to‑end)

```bash
# 1) Find a server
matrix search hello --type mcp_server --limit 3

# 2) Install with an alias
matrix install hello-sse-server --alias hello-sse-server --force --no-prompt

# 3) Run & inspect
matrix run hello-sse-server
matrix ps
matrix logs hello-sse-server -f

# 4) MCP
matrix mcp probe --alias hello-sse-server
matrix mcp call hello --alias hello-sse-server --args '{}'

# 5) Cleanup
matrix stop hello-sse-server
matrix uninstall hello-sse-server --yes
```

---

## Environment variables

```bash
export MATRIX_HUB_BASE="https://api.matrixhub.io"   # or your private Hub
export MATRIX_HUB_TOKEN="..."                       # optional
export MATRIX_HOME="$HOME/.matrix"                  # optional (defaults to ~/.matrix)
# TLS / corporate proxies
export SSL_CERT_FILE=/path/to/ca.pem
# or
export REQUESTS_CA_BUNDLE=/path/to/ca.pem
```

---

## Project links

* Website: [https://matrixhub.io](https://matrixhub.io)
* CLI: published as `matrix-cli` (PyPI/pipx)
* SDK: `matrix-python-sdk`
