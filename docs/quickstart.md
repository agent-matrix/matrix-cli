
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
matrix ps                # URL column
matrix logs hello-sse-server -f
```

## 5) MCP probe & call

```bash
# by alias (auto-discovers URL)
matrix mcp probe --alias hello-sse-server
matrix mcp call hello --alias hello-sse-server --args '{}'

# or by explicit URL
matrix mcp probe --url http://127.0.0.1:41481/messages/
```

## 6) Stop & uninstall

```bash
matrix stop hello-sse-server
matrix uninstall hello-sse-server --yes
```
