# frpdeck

`frpdeck` is a Python 3.11+ CLI for managing FRP client and server deployments from structured YAML source files. This first stage focuses on deployment and maintenance workflows: initialize instance directories, validate configs, render FRP and systemd files, apply them locally, inspect status, and upgrade binaries.

The existing [frp](./frp) directory remains in the repository only as reference material for old shell behavior. The new project does not execute those scripts at runtime. Their hardcoded `/root/frp` assumptions have been replaced by explicit path models that resolve relative to each instance directory.

## Current capabilities

- `init` creates a new client or server instance directory.
- `render` generates FRP TOML, proxy includes, and systemd units under `rendered/`.
- `validate` checks schema, placeholder values, token sources, path resolution, and simple proxy conflicts.
- `apply` validates, renders, installs binaries if needed, syncs runtime files, installs the systemd unit, and restarts the service.
- `reload` calls `frpc reload -c ...` for client instances.
- `restart` and `status` operate on the configured systemd service.
- `check-update` and `upgrade` support GitHub latest releases and offline archives.
- `doctor` checks Linux/systemd availability, instance files, and basic write permissions.

## Not implemented yet

- MCP service logic
- Web dashboard or visualization service
- Remote centralized control
- Interactive TOML editing

## Development setup

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Basic usage

Initialize a client instance:

```bash
frpdeck init client grape-networking
```

Initialize a server instance:

```bash
frpdeck init server edge-svr
```

Render generated files:

```bash
frpdeck render --instance ./examples/client-node
frpdeck render --instance ./examples/server-node
```

Validate source configuration:

```bash
frpdeck validate --instance ./examples/client-node
```

Apply an instance to the configured runtime paths:

```bash
sudo frpdeck apply --instance ./my-client
```

## Example client workflow

1. Copy `examples/client-node` to a working directory.
2. Replace `PLEASE_FILL_SERVER_ADDR` and domain placeholders in `node.yaml` and `proxies.yaml`.
3. Create `secrets/token.txt` with the real token.
4. Run `frpdeck validate --instance ./your-client`.
5. Run `frpdeck render --instance ./your-client`.
6. Run `sudo frpdeck apply --instance ./your-client`.

## Example server workflow

1. Copy `examples/server-node` to a working directory.
2. Replace `PLEASE_FILL_DOMAIN` and create `secrets/token.txt`.
3. Run `frpdeck validate --instance ./your-server`.
4. Run `frpdeck render --instance ./your-server`.
5. Run `sudo frpdeck apply --instance ./your-server`.

## Notes on paths

- Relative paths in YAML are resolved against the instance directory, not the shell working directory.
- Rendered systemd units always use absolute runtime paths.
- By default, runtime files are installed under `runtime/` inside the instance directory, while the systemd unit is written to `/etc/systemd/system`.
