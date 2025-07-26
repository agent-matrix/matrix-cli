# Commands Reference

## `matrix search`

Search the Matrix Hub catalog.

```bash
matrix search "your query" \
  [--type agent|tool|mcp_server] \
  [--capabilities cap1,cap2] \
  [--frameworks fw1,fw2] \
  [--providers p1,p2] \
  [--mode hybrid|keyword|semantic] \
  [--limit N] [--offset M] [--json]
```
* `q` (positional): free‑text search query
* `--type`: filter by entity type
* `--mode`: ranking mode (hybrid is default)
* `--json`: raw JSON output

## `matrix show`
Show details of a single entity by its UID:

```bash
matrix show agent:pdf-summarizer@1.4.2 [--json]
```
Renders name, version, type, summary, capabilities, endpoints, artifacts, adapters.

## `matrix install`
Install an entity into a project:

```bash
matrix install <id> --target <path> [--version <ver>] [--json]
```<id>` can be `type:name@version` or `type:name` with `--version`.
Writes adapters, registers with MCP-Gateway, and produces `matrix.lock.json`.

## `matrix list`
List entities from Hub or Gateway:

```bash
matrix list [--type <type>] [--source hub|gateway] [--limit N]
```
* `--source=hub` queries the catalog index.
* `--source=gateway` queries your MCP‑Gateway registrations.

## `matrix remotes`
Manage catalog remotes:

```bash
# List all
matrix remotes list [--json]

# Add a new remote
matrix remotes add <url> [--name <name>] [--json]

# Trigger ingest of a remote
matrix remotes ingest <name> [--json]
```
