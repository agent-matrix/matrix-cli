
<!-- docs/troubleshooting.md -->

# Troubleshooting

## "ExceptionGroup: unhandled errors in a TaskGroup"

Usually means the CLI couldn’t establish an MCP session.

**Checklist**

1. **Is the server running?**

   * Probe the URL directly: `curl -I http://127.0.0.1:6288/sse` (look for `200 OK`).
   * Try `matrix mcp probe --url ... --json` and inspect the error.
2. **Endpoint mismatch**

   * Your server exposes `/sse`, older code might use `/messages/`.
   * The CLI retries once with the alternate path automatically.
3. **Tool name mismatch**

   * Server exposes `chat`, but you called `watsonx-chat`.
   * The CLI now prints tool names on failures.
4. **Stale lock**

   * If `matrix run` says locked, run `matrix stop <alias>` or remove `~/.matrix/state/<alias>/runner.lock.json`.
5. **TLS / corporate CA**

   * Set `SSL_CERT_FILE` *or* `REQUESTS_CA_BUNDLE` to your CA bundle.

## Gateway 401 during install

Set `MCP_GATEWAY_TOKEN` or pass `--gw-token` in your PoC scripts.

## Local wheels

Ensure your virtualenv resolves your dev wheels first, e.g. install `matrix-python-sdk-*.whl` before `matrix-cli`.

