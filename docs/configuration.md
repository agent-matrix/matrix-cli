# Configuration

Matrix CLI loads configuration from:

1. **TOML file**: `~/.matrix/config.toml`  
2. **Environment variables**:
   - `MATRIX_BASE_URL`, `MATRIX_TOKEN`  
   - `MCP_GATEWAY_URL`, `MCP_GATEWAY_TOKEN`  
   - `MATRIX_CACHE_DIR`, `MATRIX_CACHE_TTL`  
3. **CLI flags**: `--base-url`, `--token`

#### Sample `~/.matrix/config.toml`

```toml
[registry]
base_url = "http://localhost:7300"
token = "..."

[gateway]
base_url = "http://localhost:7200"
token = "..."

[cache]
dir = "~/.cache/matrix"
ttl_seconds = 14400
```
