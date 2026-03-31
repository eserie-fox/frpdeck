# Development

## Prerequisites

- Python 3.11+
- Linux environment for full systemd- and FRP-related command coverage
- A virtual environment is recommended

Typical setup:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Tests

Run the test suite with:

```bash
pytest
```

Useful focused runs:

```bash
pytest tests/test_cli.py
pytest tests/test_mcp_server.py
pytest tests/test_proxy_manager.py
```

If the local environment is missing test dependencies, install the `dev` extra first.

## Build

Build source and wheel artifacts with standard setuptools tooling, for example:

```bash
python -m pip install build
python -m build
```

Current package data includes:

- Jinja templates under `src/frpdeck/templates/`
- config default JSON resources under `src/frpdeck/config_defaults/`

These JSON files are runtime-critical resources. In particular:

- operational defaults come from `node_client.json`, `node_server.json`, and `proxy_file.json`
- scaffold data is layered as operational defaults plus `scaffold_*_overrides.json`
- scaffold assets currently include `scaffold_instance_layout.json` and `scaffold_token_example.json`
- packaging changes must keep `config_defaults/*.json` in the built artifacts

## Release Notes

- Do not bump the project version unless the task explicitly asks for it
- Keep package data in sync with new config defaults
- README and `docs/` should move together with config-shape changes

## Local MCP Testing

Generic server:

```bash
python -m frpdeck.mcp.server
```

Bound server:

```bash
python -m frpdeck.mcp.server --instance-dir /path/to/instance
```

Recommended workflow is still to generate a bound wrapper:

```bash
frpdeck mcp install-stdio-wrapper --instance /path/to/instance
```

Then manually run the generated wrapper over SSH before configuring an MCP client.

## Current Design Constraints

- Keep one instance-centric config model
- Do not reintroduce a separate frpdeck runtime-config layer in this phase
- Keep FRP logging (`client.log` / `server.log`) separate from frpdeck logging (`frpdeck_logging`)
- Keep business logic in `services`, not in CLI or MCP adapters
- Defaults should come from package JSON resources rather than scattered inline literals
- Scaffold config should be `operational defaults + scaffold overrides`, not a second full copy of node/proxy defaults
- The instance directory skeleton should come from `config_defaults/scaffold_instance_layout.json`, not a hard-coded list in `scaffold.py`
- `frpdeck_logging.stream` is fixed to `stderr`, `stdout`, or `none`; default values come from package defaults and currently resolve to `stderr`
- `frpdeck_logging.level` uses Python logging level names, while FRP `log.level` uses FRP's own lowercase value set
- With an instance context, instance logging initialization is fail-fast; do not silently skip broken logging config
- FRP log levels are constrained to `trace`, `debug`, `info`, `warn`, and `error`
- Keep logging config loading separate from logger mutation: load/resolve first, apply second

## Config Evolution Policy

Configuration changes are not forward-compatible by policy right now.

- Do not add migration layers unless explicitly requested
- Do not preserve unused legacy fields “just in case”
- When config shape changes, update defaults, scaffold resources, tests, README, and `docs/` in the same change

## Verification Notes

- `pytest` is the primary verification path when dev dependencies are installed
- `python -m build` is optional smoke coverage for release artifacts when the `build` module is available
- Even when `build` is unavailable locally, keep package-resource smoke tests for `config_defaults/*.json` in the test suite
