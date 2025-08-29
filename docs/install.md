<!-- docs/install.md -->

# Install

**Requirements**: Python **3.11+**.

## Recommended

```bash
pipx install matrix-cli
```

## Virtualenv

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install matrix-cli
```

## Optional extras

```bash
# MCP client utilities (SSE OK; WS needs websockets)
pip install "matrix-cli[mcp]"
# Developer tools (lint/test/docs)
pip install "matrix-cli[dev]"
```

## Upgrading

```bash
pipx upgrade matrix-cli
# or
pip install -U matrix-cli
```

## Using local wheels (offline/dev)

If you built local wheels (e.g. the SDK: `matrix-python-sdk-0.1.6`), install them before the CLI:

```bash
pip install /path/to/wheelhouse/matrix_python_sdk-0.1.6-py3-none-any.whl
pip install matrix-cli==0.1.3
```
