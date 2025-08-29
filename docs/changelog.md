
<!-- docs/changelog.md -->

# Changelog

## v0.1.3

* **Connector runner** supported end‑to‑end (pid=0; URL only)
* MCP client: one‑retry tolerance between `/sse` and `/messages/`
* Better error messages: show advertised tool names on call failure
* Runtime: `stop` is a no‑op for connectors; `doctor` acknowledges remote URL

## v0.1.2

* `matrix connection` (human/JSON; exit code 0/2)
* `matrix mcp` (probe/call; SSE; WS optional)
* Safer installs (no absolute paths leaked to the Hub)
* `matrix ps` shows URL; `--plain` & `--json`
* `matrix uninstall` with optional `--purge`
* TLS hardening
