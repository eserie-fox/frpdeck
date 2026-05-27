# Quick Start

This guide shows the shortest path from installation to a managed FRP instance.

## Install

Install from PyPI:

```bash
pip install frpdeck
frpdeck --help
```

Install from a local checkout:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

## Client Instance

Create a client scaffold:

```bash
frpdeck init client my-client
```

Edit the generated files and secret material:

```bash
${EDITOR:-vi} ./my-client/node.yaml
${EDITOR:-vi} ./my-client/proxies.yaml
mkdir -p ./my-client/secrets
printf 'replace-me\n' > ./my-client/secrets/token.txt
```

Replace `PLEASE_FILL_SERVER_ADDR`, token placeholders, and sample proxy domains before applying.

Validate, render, and apply:

```bash
frpdeck validate --instance ./my-client
frpdeck render --instance ./my-client
frpdeck apply --instance ./my-client --sudo
```

Inspect runtime state:

```bash
frpdeck status --instance ./my-client
```

If you want to mirror rendered config without restarting anything, run:

```bash
frpdeck sync --instance ./my-client --sudo
```

For offline install or replacement from a local FRP archive:

```bash
frpdeck apply --instance ./my-client --archive /path/to/frp_0.65.0_linux_amd64.tar.gz --sudo
```

## Server Instance

Create a server scaffold:

```bash
frpdeck init server my-server
```

Create the token file and edit `node.yaml`:

```bash
mkdir -p ./my-server/secrets
printf 'replace-me\n' > ./my-server/secrets/token.txt
${EDITOR:-vi} ./my-server/node.yaml
```

If you need FRP vhost routing, explicitly set `server.vhost_http_port`, `server.vhost_https_port`, and/or `server.subdomain_host`.

Validate, render, and apply:

```bash
frpdeck validate --instance ./my-server
frpdeck render --instance ./my-server
frpdeck apply --instance ./my-server --sudo
```

## Common Command Order

- `validate` checks source config and does not write generated files.
- `render` writes generated files under `rendered/`.
- `sync` mirrors rendered files into `runtime/config` without restarting.
- `apply` runs the full local workflow: validate, render, sync, install or upgrade the binary, install the systemd unit, and restart the service.
- `status` reports the configured systemd service and rendered proxy state.

All mutating commands support `--sudo`. When a non-root user passes `--sudo`, `frpdeck` re-execs the full command via sudo before loading instance config or touching managed files.

## Next Steps

- Read [`README.md`](README.md) for feature overview and command semantics.
- Read [`docs/configuration.md`](docs/configuration.md) for config shape, defaults, paths, and logging.
- Read [`docs/development.md`](docs/development.md) for local development and verification.
