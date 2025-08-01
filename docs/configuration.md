<!-- docs/configuration.md -->
# Configuration

Matrix CLI loads configuration from (in order of precedence):

1. **Environment variables**
2. **TOML file** at `~/.matrix/config.toml` (override via `MATRIX_CONFIG`)
3. **Built-in defaults**

You can also override per command using **CLI flags** like `--base-url` and `--token`.

---

## TOML Schema

```toml
[registry]
base_url = "http://localhost:7300"
token = "..."                    # optional
extra_catalogs = ["https://...", "https://..."]  # optional

[gateway]
base_url = "http://localhost:7200"
token = "..."                    # optional

[cache]
dir = "~/.cache/matrix"
ttl_seconds = 14400
```

> If `MATRIX_CACHE_DIR` is not set and the config omits `cache.dir`, the CLI honors `XDG_CACHE_HOME` and uses `$XDG_CACHE_HOME/matrix`.

---

## Environment Variables

| Variable                | Purpose                             |
| ----------------------- | ----------------------------------- |
| `MATRIX_BASE_URL`       | Hub base URL (registry)             |
| `MATRIX_TOKEN`          | Hub bearer token                    |
| `MATRIX_EXTRA_CATALOGS` | CSV list of additional catalog URLs |
| `MCP_GATEWAY_URL`       | Gateway base URL                    |
| `MCP_GATEWAY_TOKEN`     | Gateway bearer token                |
| `MATRIX_CACHE_DIR`      | Local cache directory               |
| `MATRIX_CACHE_TTL`      | TTL (seconds) for cache entries     |
| `MATRIX_CONFIG`         | Path to alternate TOML config       |

---

## CLI Flags

| Flag         | Description                             |
| ------------ | --------------------------------------- |
| `--base-url` | Override registry base URL for this run |
| `--token`    | Override registry bearer token          |
| `--verbose`  | Print effective configuration summary   |

Example:

```bash
matrix --base-url http://hub.example.com --token "$MATRIX_TOKEN" search "ocr"
```
