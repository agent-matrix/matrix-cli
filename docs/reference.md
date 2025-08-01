<!-- docs/reference.md -->
# API & Internals Reference

This section explains how the CLI talks to the backend and how components fit together.

---

## Architecture

```

Matrix CLI  ──► Matrix Python SDK ──► Matrix Hub (FastAPI)
▲
└── Optional local cache (ETag/TTL)

```

- **Matrix Hub (FastAPI)** exposes:
  - `GET /health`
  - `GET /catalog/search`
  - `GET /catalog/entities/{id}`
  - `POST /catalog/install`
  - `GET /catalog/remotes`
  - `POST /catalog/remotes`
  - `DELETE /catalog/remotes?url=...`
  - `POST /catalog/ingest?remote=...`

- **Matrix Python SDK** wraps these with a typed client:
  - `search(q, type, **filters)`
  - `get_entity(id)`
  - `install(id, …)`
  - `list_remotes()`, `add_remote(url)`, `delete_remote(url)`
  - `trigger_ingest(name?)`

- **Matrix CLI** maps subcommands to SDK calls and formats output using **Rich**.

---

## Authentication

If your Hub requires auth, set `MATRIX_TOKEN` (or use `--token`).  
The CLI/SDK sends `Authorization: Bearer <token>` to protected endpoints (install, remotes, ingest).

---

## Caching

The SDK can maintain an optional cache (ETag/TTL) under `cache.dir`.  
Configure TTL via `cache.ttl_seconds` or `MATRIX_CACHE_TTL`.

---

## Exit codes

- `0` success
- `1` usage error (bad flags/args)
- `2` API/network error
- `130` interrupted (Ctrl-C)

---

## REPL behavior

- Help does not clear the screen.
- Redundant `matrix` at the head is accepted (e.g., `matrix exit`).
- Options-first parsing supported (`--no-rain`, `--version`).
- `screensaver` uses the same animation as startup and preserves prior output.
- `exit`, `quit`, `close` or `matrix exit` leave the REPL cleanly.

---

## Compatibility & Versions

- Python **3.11+** recommended  
- CLI version can be shown via `matrix --version`  
- Hub/SDK updates are generally backward compatible at the REST boundary
```

---

### How to build the docs locally

```bash
pip install mkdocs mkdocs-material
mkdocs serve
```

Open `http://127.0.0.1:8000/`.

If you want badges, CI pipelines, or translated navigation, say the word and I’ll extend this to a full documentation site structure (FAQ, tutorials, examples, SDK reference pointers).
