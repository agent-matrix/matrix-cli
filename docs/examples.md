# Examples

A quick, hands-on tutorial for using **Matrix CLI** with real commands you can copy-paste.

> Requires Python 3.11+. Install with `pipx install matrix-cli` (or `pip install matrix-cli`).

---

## 1) Configure once

Create `~/.matrix/config.toml`:

```toml
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

Environment overrides (optional):

```bash
export MATRIX_BASE_URL=http://hub.example.com
export MATRIX_TOKEN=...
```

---

## 2) Explore the REPL (interactive shell)

```bash
matrix
```

Useful actions inside the shell:

```text
help                 # show commands
help search          # detailed help for a command
clear                # clear screen
--no-rain            # disable startup animation for this session
screensaver          # matrix rain; press any key to return
exit                 # or: quit / close
```

> You can type a redundant leading `matrix` if you like: `matrix exit`.

---

## 3) One-shot usage (no shell)

```bash
matrix --version
matrix --help
matrix search "langchain" --type tool --limit 5
```

To run and exit without entering the shell:

```bash
matrix --no-repl --help
```

---

## 4) Search, inspect, install

**Search**

```bash
matrix search "summarize pdfs" \
  --type agent \
  --capabilities pdf,summarize \
  --frameworks langgraph \
  --limit 10
```

**Inspect one result**

```bash
matrix show agent:pdf-summarizer@1.4.2
# or JSON:
matrix show agent:pdf-summarizer@1.4.2 --json
```

**Install into a project**

```bash
matrix install agent:pdf-summarizer@1.4.2 \
  --target ./apps/pdf-bot
```

---

## 5) List entities

From **Matrix Hub**:

```bash
matrix list --type tool --source hub
```

From **MCP-Gateway**:

```bash
matrix list --type tool --source gateway
```

---

## 6) Manage catalog remotes

```bash
# List configured remotes
matrix remotes list

# Add a remote index
matrix remotes add https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json \
  --name official

# Trigger ingest from a specific remote
matrix remotes ingest official

# Remove a remote
matrix remotes remove --url https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json
```

---

## 7) Use in scripts

Grab JSON with `--json` and parse with `jq`.

```bash
# Bash script example
results=$(matrix search "ocr table" --type tool --json)
tool_id=$(echo "$results" | jq -r '.items[0].id')
matrix install "$tool_id" --target ./apps/data-pipeline
```

Return codes (useful in CI):

* `0` success
* `1` usage error
* `2` API/network error
* `130` interrupted

---

## 8) Tips & troubleshooting

* **Auth**: set `MATRIX_TOKEN` if your Hub requires it.
* **Cache**: speed up repeated queries by setting `MATRIX_CACHE_DIR` and `MATRIX_CACHE_TTL`.
* **Help doesn’t clear** the screen; use `clear` when you want a fresh view.
* **Screensaver**: same animation as startup; press any key to return; your previous output remains.