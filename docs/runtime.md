<!-- docs/runtime.md -->

# Runtime (run / ps / logs / stop)

## Run

```bash
matrix run <alias>
```

* For **process** runners, CLI launches the server and writes a lock with real PID/port.
* For **connector** runners, CLI writes a lock with `pid=0`, `port=null`, `url=<runner.url>`.

## List

```bash
matrix ps
matrix ps --plain     # script‑friendly (alias pid port uptime url target)
matrix ps --json
```

## Logs

```bash
matrix logs <alias> [-f]
```

## Health

```bash
matrix doctor <alias>
```

* Process: probes `/health` at `http://127.0.0.1:<port>/health`.
* Connector: returns **ok** with a message like *configured remote SSE url …* (may perform a short HEAD).

## Stop

```bash
matrix stop <alias>
```

* Process: sends SIGTERM and removes the lock.
* Connector: **no‑op** (removes the lock only).
