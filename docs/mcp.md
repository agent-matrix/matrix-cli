<!-- docs/mcp.md -->

# MCP (Probe & Call)

Matrix CLI speaks **Model Context Protocol** (MCP) over **SSE** and optionally WebSocket.

## Two ways to attach

* **Process runner** — CLI starts a local server from `runner.json` (type `python`/`node`).
* **Connector runner** — CLI records a **remote** `url` (pid=0) and does **not** spawn a process.

Both are supported and non‑breaking.

## Probe

```bash
# prefer alias (discovers url/endpoint)
matrix mcp probe --alias <alias>

# explicit URL
matrix mcp probe --url http://127.0.0.1:52305/messages/

# JSON (CI)
matrix mcp probe --url http://127.0.0.1:52305/messages/ --json
```

CLI will automatically retry **once** if `/sse` vs `/messages/` is mismatched.

## Call a tool

```bash
matrix mcp call <tool_name> --alias <alias> --args '{}'
# or
matrix mcp call <tool_name> --url http://127.0.0.1:52305/sse --args '{"query":"Hi"}'
```

> **Tip**: If a call fails, the CLI prints the tool list advertised by the server (e.g., `chat`).

## Example: connector runner

Create `~/.matrix/runners/watsonx-chat/0.1.0/runner.json`:

```json
{
  "type": "connector",
  "name": "watsonx-chat",
  "description": "Connector to Watsonx MCP over SSE",
  "integration_type": "MCP",
  "request_type": "SSE",
  "url": "http://127.0.0.1:6289/sse",
  "endpoint": "/sse",
  "headers": {}
}
```

Then:

```bash
matrix run watsonx-chat   # records pid=0, shows URL; no local process is spawned
matrix mcp probe --alias watsonx-chat
matrix mcp call chat --alias watsonx-chat --args '{"query":"Hello"}'
```
