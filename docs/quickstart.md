<!-- docs/quickstart.md -->

# Quickstart

## 1) Check the Hub

```bash
matrix connection
matrix connection --json
```

## 2) Search the catalog

```bash
matrix search "hello" --type mcp_server --limit 5
matrix search "vector" --mode hybrid --with-snippets --limit 3
```

## 3) Install safely

```bash
matrix install hello-sse-server --alias hello-sse-server --force --no-prompt
```

## 4) Run + inspect

```bash
matrix run hello-sse-server
matrix ps                # URL column shows host:port and endpoint
matrix logs hello-sse-server -f
```

## 5) MCP probe & call

### By alias (auto‑discovers URL/endpoint)

```bash
matrix mcp probe --alias hello-sse-server

# Common input forms (pick one):
matrix mcp call hello --alias hello-sse-server --text "Say hello to Genoa"
matrix mcp call hello --alias hello-sse-server --kv name=world
matrix mcp call hello --alias hello-sse-server --args '{"name":"world"}'
# from stdin
echo '{"name":"world"}' | matrix mcp call hello --alias hello-sse-server --args @-
```

### By explicit URL

```bash
# If your server exposes /messages/
matrix mcp probe --url http://127.0.0.1:41481/messages/

# If your server exposes /sse/ (many MCP servers do), note the trailing slash:
matrix mcp probe --url http://127.0.0.1:41481/sse/

# Call with explicit URL and JSON args
matrix mcp call hello --url http://127.0.0.1:41481/sse/ --args '{"name":"world"}'
```

> **Tip (bash/WSL):** Wrap JSON in **single quotes** so you don’t have to escape the inner double quotes.

## 6) Stop & uninstall

```bash
matrix stop hello-sse-server
matrix uninstall hello-sse-server --yes
```
