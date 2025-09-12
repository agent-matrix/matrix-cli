# `do` — One‑shot MCP Call

A fast, zero‑JSON way to call an MCP tool exposed by a running server. You give an **alias** (or a full **URL**) and optional **text** or a **file path**; `do` selects a sensible tool and builds the arguments for you.

> Prefer `do` for quick ad‑hoc prompts. If you need structured input, use [`matrix mcp call`](./mcp.md) with `--args`, `--kv`, `--text`, or `--wizard`.

---

## Synopsis

```bash
matrix do [TARGET] [TEXT] [--alias ALIAS | --url URL] [--in PATH] [--timeout SEC] [--json]
```

**Positional arguments**

* `TARGET`  — Optional alias or catalog name you installed earlier (same as `--alias`).
* `TEXT`    — Optional plain‑text input mapped to the tool’s default input field.

**Options**

* `--alias ALIAS`  — Alias shown by `matrix ps`. Auto‑discovers host/port/endpoint.
* `--url URL`      — Full SSE/WebSocket endpoint (e.g., `http://127.0.0.1:52305/messages/`).
* `--in PATH`      — Path‑like input. If the schema defines `path`/`file` fields, it maps there; otherwise it uses the default input key.
* `--timeout SEC`  — Connect/read timeout (default: `10.0`).
* `--json`         — Emit structured JSON instead of human text.

Exit codes: `0` success · `2` user/guidance error · `130` interrupted

---

## What `do` infers for you

### URL / endpoint (from alias)

* Reuses the same discovery helpers as `matrix mcp`:

  * Finds the running row for the alias via `matrix_sdk.runtime.status()`.
  * If you did **not** provide an endpoint, it reads `<target>/runner.json` and falls back to `"/messages/"` when unspecified.
  * Builds `http://{host}:{port}/{endpoint}/` and picks **SSE** automatically for HTTP(S) URLs.
* If you pass `--url`, it is used **as‑is**. Many MCP servers require a **trailing slash** (e.g., `/sse/`).

### Tool selection

* Picks a *default* tool by name preference: **`default` → `main` → `run` → `chat`**.
* If none match, uses the **first** tool exposed by the server.

### Input mapping

* If you provided **`TEXT`**, `do` maps it to a default input key inferred from the tool’s input schema:

  1. `x-default-input`
  2. first of `query | prompt | text | input | message`
  3. a single **required** string property
  4. the only **string** property
* If you provided **`--in PATH`**, `do` prefers common path keys (`path`, `file`, `filepath`, `filename`, `input_path`); otherwise it maps PATH to the default input key (above).
* If the schema requires structured input and `do` can’t infer it safely, it will guide you to use `matrix mcp call --wizard`.

### Output rendering

* Prints text content blocks directly. Non‑text blocks are shown as `- <type>: <repr>`. Use `--json` for machine‑readable output.

---

## Examples

### 1) Quick chat‑style prompt (alias)

```bash
# Assume you already ran: matrix run watsonx-chat
matrix do watsonx-chat "List three famous landmarks in Genoa"
```

### 2) Using TARGET positional instead of --alias

```bash
matrix do hello-sse-server "Say hello to Genoa"
```

### 3) Explicit URL (note the trailing slash)

```bash
matrix do --url http://127.0.0.1:40091/sse/ "What is the capital of Italy?"
```

### 4) File path mapping

```bash
# If the tool schema has a `path` or `file` field, --in maps there automatically
matrix do data-processor --alias data-processor --in ./data/input.csv
```

### 5) JSON output (pipe into jq)

```bash
matrix do watsonx-chat "Hi" --json | jq '.content'
```

---

## Troubleshooting

**“Provide --url OR --alias (optionally with --port).”**
You didn’t supply a way to connect. Add `--alias <name>` (preferred) or `--url http://host:port/path/`.

**404 or route error**
If you passed `--url` without a trailing slash (e.g., `/sse`), many servers expect `/sse/`.

**“Multiple inputs or no clear default input detected.”**
The tool needs structured arguments. Use the guided mode:

```bash
matrix mcp call <tool> --alias <alias> --wizard
```

**“No tools exposed by the server.”**
Verify the server is healthy and actually exposes tools. Try:

```bash
matrix mcp probe --alias <alias>
```

**Unsupported URL scheme**
WebSocket requires `ws://` or `wss://`. HTTP(S) uses SSE by default.

---

## When to use `do` vs `mcp call`

* Use **`do`** for quick one‑shot prompts where a single text or file path is enough.
* Use **`mcp call`** when you need full control over arguments (`--args` JSON, `--kv`, `--text`, or interactive `--wizard`).

---

## See also

* [`mcp` command](./mcp.md)
* [`quickstart`](./quickstart.md)
* `matrix ps`, `matrix run`, `matrix logs`, `matrix stop`
