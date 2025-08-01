<!-- docs/commands.md -->
# Commands

This page shows common commands and options. All commands are available **one-shot** or inside the **REPL**.

> Inside the REPL, `matrix` as a leading token is optional — `matrix exit` and `exit` both work.

---

## Global options (group)

- `--version` – print CLI version and exit  
- `--rain / --no-rain` – toggle startup animation  
- `--no-repl` – run requested action (e.g., `--help`) and exit  
- `--help` – show top-level help

In REPL, options-first is supported (e.g., `--no-rain`).

---

## search

Search the Hub catalog.

```bash
matrix search "summarize pdfs" \
  --type agent \
  --capabilities pdf,summarize \
  --frameworks langgraph \
  --mode hybrid \
  --limit 10
```

**Common flags**

| Flag             | Description                     |
| ---------------- | ------------------------------- |
| `--type`         | Filter by entity type           |
| `--capabilities` | Comma-separated capability list |
| `--frameworks`   | Filter by frameworks            |
| `--mode`         | Search mode (e.g., hybrid)      |
| `--limit`        | Max results                     |
| `--json`         | Raw JSON output                 |

---

## show

Display full metadata for an entity.

```bash
matrix show agent:pdf-summarizer@1.4.2 [--json]
```

Supports both `type:name@version` and `type:name` (with `--version` flag where applicable).

---

## install

Install an agent/tool into your project.

```bash
matrix install agent:pdf-summarizer@1.4.2 \
  --target ./apps/pdf-bot
```

Writes adapters, registers with MCP-Gateway (if configured), and creates `matrix.lock.json`.

---

## list

List entities from Hub or Gateway.

```bash
# From Hub index
matrix list --type tool --source hub

# From MCP-Gateway
matrix list --type tool --source gateway
```

---

## remotes

Manage catalog remotes.

```bash
# List
matrix remotes list

# Add
matrix remotes add https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json \
  --name official

# Remove
matrix remotes remove --url https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json

# Trigger ingest
matrix remotes ingest official
```

---


---

## REPL helpers

```bash
help                  # or: matrix help
help <command>
clear                 # or: matrix clear
exit | quit | close   # or: matrix exit
```

