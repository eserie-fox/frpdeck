# frpdeck

`frpdeck` is a lightweight Python 3.11+ CLI for managing FRP instances from structured source files. It focuses on practical single-host operations: initialize instance directories, validate configuration, render generated artifacts, sync managed runtime files, apply changes locally, inspect state, and maintain structured proxy definitions without introducing a larger control plane.

It is also MCP-friendly. `frpdeck` includes a local stdio MCP thin wrapper so an LLM can assist with structured proxy maintenance against one bound instance directory at a time.

## Highlights

- Lightweight FRP deployment and maintenance workflows for client and server instances.
- Structured proxy management backed by `proxies.yaml`, with import, typed add, update, remove, and preview support.
- Stable JSON outputs for automation and scripting.
- Append-only audit logging and revision snapshots for write operations.
- Local stdio MCP support for LLM-assisted proxy maintenance.

## Installation

Install from PyPI:

```bash
pip install frpdeck
frpdeck --help
```

Install from source when you want a local checkout:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

For development:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Documentation

Key design notes now live under `docs/`:

- [`docs/architecture.md`](docs/architecture.md): layer boundaries and dependency direction
- [`docs/configuration.md`](docs/configuration.md): instance config shape, defaults, path resolution, and logging semantics
- [`docs/development.md`](docs/development.md): local development, tests, packaging, and MCP testing
- [`docs/release.md`](docs/release.md): version bump, build, and tag/publish checklist
- [`CHANGELOG.md`](CHANGELOG.md): release history

## Features

- `init` creates a new client or server instance directory.
- `validate` checks source config only: schema, placeholder values, token sources, path resolution, and simple proxy conflicts.
- `render` generates FRP TOML, proxy includes, and systemd units under `rendered/` only.
- `sync` mirrors managed files from `rendered/` into `runtime/config` only.
- `reload` calls `frpc reload -c ...` for client instances using the current `runtime/config`.
- `apply` validates, renders, syncs runtime files, installs binaries if needed, installs the systemd unit, and restarts the service.
- `restart` and `status` operate on the configured systemd service.
- `check-update` and `upgrade` support GitHub latest releases and offline archives.
- `doctor` checks Linux/systemd availability, instance files, and basic write permissions.
- `python -m frpdeck.mcp.server` starts a local stdio MCP server that exposes proxy-management tools and read-only status resources.

## Current scope

`frpdeck` is a focused operations tool, not a full FRP control platform. It currently centers on structured instance management, proxy maintenance, local apply workflows, auditing, and MCP-assisted maintenance. HTTP control planes, remote auth layers, and web dashboards are intentionally out of scope for now.

## Non-goals

- Remote HTTP transport for MCP
- Authentication or authorization for remote MCP access
- Web dashboard or visualization service
- Remote centralized control
- Interactive TOML editing

## Quick start

Running `frpdeck` with no arguments now shows the built-in command help, including common entry points such as `init`, `apply`, `proxy`, `status`, and `python -m frpdeck.mcp.server`.

Initialize a client instance:

```bash
frpdeck init client my-client
```

The generated client scaffold includes a sample HTTP proxy in `proxies.yaml` so the route fields are visible in the initial config shape.

Edit the generated configuration and secret material:

```bash
${EDITOR:-vi} ./my-client/node.yaml
${EDITOR:-vi} ./my-client/proxies.yaml
mkdir -p ./my-client/secrets
printf 'replace-me\n' > ./my-client/secrets/token.txt
```

`instance_name` is the logical identity stored in `node.yaml`. It may differ from the directory name; status, service naming defaults, and audit data use `instance_name`, not `instance_dir.name`.

Validate the source configuration:

```bash
frpdeck validate --instance ./my-client
```

Render generated files:

```bash
frpdeck render --instance ./my-client
```

Mirror the rendered snapshot into runtime config without restarting anything:

```bash
sudo frpdeck sync --instance ./my-client
```

Apply an instance to the configured runtime paths:

```bash
sudo frpdeck apply --instance ./my-client
```

For offline install or replacement from a local FRP archive:

```bash
sudo frpdeck apply --instance ./my-client --archive /path/to/frp_0.65.0_linux_amd64.tar.gz
```

Inspect runtime state:

```bash
frpdeck status --instance ./my-client
```

Apply emits stage-by-stage progress in text mode so it is clear when validation, rendering, binary download/install, runtime sync, systemd install, and restart are happening.

## Command semantics

- `validate` reads `node.yaml` and `proxies.yaml`, validates them, and exits. It does not write `rendered/` or `runtime/config`.
- `render` writes the full generated snapshot into `rendered/`. It does not touch `runtime/config`, reload FRP, or restart systemd.
- `sync` mirrors the managed rendered snapshot into `runtime/config`. It does not run validation, rendering, reload, or restart logic.
- `reload` asks `frpc` to reload using the current `runtime/config`. If runtime config is missing, run `sync` or `apply` first.
- `apply` is the full operational path: validate, render, sync, install/upgrade the managed binary if needed, install the systemd unit, and restart the service.
- `proxy preview` is a temporary client-side preview of proxy include output. It does not modify `rendered/`. Top-level `render` writes the full instance snapshot into `rendered/`.

Uninstall installed artifacts while keeping source configuration:

```bash
frpdeck uninstall --instance ./my-client
```

Delete the instance directory as well:

```bash
frpdeck uninstall --instance ./my-client --purge
```

## Typical workflows

### Client instance

1. Run `frpdeck init client your-client`.
2. Replace `PLEASE_FILL_SERVER_ADDR` and domain placeholders in `node.yaml` and `proxies.yaml`.
3. Create `secrets/token.txt` with the real token.
4. Run `frpdeck validate --instance ./your-client`.
5. Run `frpdeck render --instance ./your-client`.
6. Run `sudo frpdeck apply --instance ./your-client`.
7. Run `frpdeck status --instance ./your-client`.

For offline binary management, `apply --archive`, `upgrade --archive`, and `binary.local_archive` are all supported.

### Server instance

1. Run `frpdeck init server your-server`.
2. Create `secrets/token.txt`.
3. If you want FRP vhost routing, explicitly set `server.vhost_http_port` and/or `server.vhost_https_port` in `node.yaml`.
4. If you want subdomain-based routing, also set `server.subdomain_host`.
5. Run `frpdeck validate --instance ./your-server`.
6. Run `frpdeck render --instance ./your-server`.
7. Run `sudo frpdeck apply --instance ./your-server`.

## Server vhost modes

By default, a new server instance does not set `server.vhost_http_port`, `server.vhost_https_port`, or `server.subdomain_host`.

- With the default scaffold, rendered `frps.toml` does not bind `80` or `443` and does not enable subdomain host handling.
- When you explicitly set `server.vhost_http_port` or `server.vhost_https_port`, `frpdeck` renders those values into `frps.toml`.
- When you explicitly set `server.subdomain_host`, `frpdeck` renders `subDomainHost`.

Example server config with vhost enabled:

```yaml
server:
  bind_addr: 0.0.0.0
  bind_port: 7000
  vhost_http_port: 80
  vhost_https_port: 443
  subdomain_host: frp.example.com
  log:
    to: runtime/logs/frps.log
    level: info
    max_days: 7
    disable_print_color: true
  auth:
    method: token
    token_file: secrets/token.txt
```

## HTTP/HTTPS proxies

Client proxy definitions for `http` and `https` stay in `proxies.yaml` with the existing snake_case source config style.

HTTP with `custom_domains`:

```yaml
proxies:
  - name: app_http
    type: http
    local_ip: 127.0.0.1
    local_port: 8080
    custom_domains:
      - app.example.com
```

HTTPS with `custom_domains`:

```yaml
proxies:
  - name: app_https
    type: https
    local_ip: 127.0.0.1
    local_port: 8443
    custom_domains:
      - secure.example.com
```

HTTP with `subdomain`:

```yaml
proxies:
  - name: app_subdomain
    type: http
    local_ip: 127.0.0.1
    local_port: 8080
    subdomain: app
```

`custom_domains` and `subdomain` may be set together. That is supported by the implementation, although in practice it is usually clearer to choose the one that matches the deployment pattern.

`http` and `https` proxies must define at least one of:

- `custom_domains`
- `subdomain`

Blank strings are rejected for `custom_domains`, `subdomain`, and `server.subdomain_host`.

### Proxy CLI shortcuts

Import one proxy mapping from a YAML file:

```bash
frpdeck proxy import ./app-http.yaml --instance ./my-client
```

Update one existing proxy from a YAML patch file:

```bash
frpdeck proxy update ssh ./ssh-patch.yaml --instance ./my-client
```

Add an HTTP proxy with one or more custom domains:

```bash
frpdeck proxy add http \
  --instance ./my-client \
  --name app-http \
  --local-port 8080 \
  --custom-domain app.example.com \
  --custom-domain www.example.com
```

Add an HTTPS proxy:

```bash
frpdeck proxy add https \
  --instance ./my-client \
  --name app-https \
  --local-port 8443 \
  --custom-domain secure.example.com
```

Add an HTTP proxy using a subdomain:

```bash
frpdeck proxy add http \
  --instance ./my-client \
  --name app-subdomain \
  --local-port 8080 \
  --subdomain app
```

`--custom-domain` is repeatable, and it can be combined with `--subdomain` when you want both selectors on the same proxy.

## MCP

`frpdeck` ships with a local stdio MCP thin wrapper over structured proxy CRUD, import, and preview tools plus read-only status resources. It is designed to bind to one instance directory at a time and is best used through a generated wrapper script.

Recommended workflow: generate a bound wrapper script with `frpdeck mcp install-stdio-wrapper` and point your MCP client at that script. Prefer the generated wrapper over writing your own unless you have a specific reason to customize startup behavior. The wrapper binds to your chosen instance directory and, by default, embeds the Python interpreter running `frpdeck` when the script is created. Use `--python /path/to/python` if you need to override that explicitly.

In practice, wrapper scripts are most commonly generated for client instances, because proxy configuration is usually managed on the client side. That is a usage pattern rather than a hard restriction: the MCP wrapper is tied to an instance directory, not to a separate client-only mode in the documentation.

### Recommended MCP setup

On the FRP machine, change into your instance directory and generate the wrapper:

```bash
cd /path/to/your-instance
frpdeck mcp install-stdio-wrapper
```

This is equivalent to:

```bash
frpdeck mcp install-stdio-wrapper --instance /path/to/your-instance
```

The command writes `/path/to/your-instance/start-mcp-stdio.sh`, binds that script to the resolved absolute instance path, and embeds the Python interpreter that is running `frpdeck` at generation time. Replace the example path with your own instance directory.

If you need to start the server manually without the wrapper, you can still use:

```bash
python -m frpdeck.mcp.server
```

For a bound one-instance server, the direct form is:

```bash
python -m frpdeck.mcp.server --instance-dir /path/to/your-instance
```

Before configuring Claude Code, manually verify the SSH command from the Claude Code machine. Replace the host name and path with your own SSH destination and instance directory:

```bash
ssh your-ssh-host /path/to/your-instance/start-mcp-stdio.sh
```

That command should normally stay attached and wait for stdin/stdout traffic because the MCP stdio server is waiting for client messages. If it exits immediately or prints an error, fix the remote Python environment, instance path, or SSH setup first.

Once the manual SSH command works, add the MCP entry in Claude Code:

```bash
claude mcp add --scope user --transport stdio frpdeck -- \
  ssh your-ssh-host /path/to/your-instance/start-mcp-stdio.sh
```

Current MCP scope is intentionally small:

- Local stdio MCP server only.
- Structured proxy CRUD/import/preview only; instance-level `validate`/`sync`/`apply` stay in the CLI.
- No HTTP transport.
- No remote auth layer.
- No web UI.

## Audit and safety notes

Write operations append audit records under `state/audit/audit.jsonl`, and proxy mutations also create revision snapshots under `state/revisions/`. This is intended to make changes traceable and manually recoverable without turning the tool into a full control plane.

### SSH and BatchMode

`BatchMode yes` is useful for unattended or scripted SSH sessions because it disables interactive password prompts and host-key confirmation. Do not treat it as the first step.

Recommended order:

1. Manually run the SSH wrapper command until it works without prompts.
2. Confirm that host keys are trusted and key-based auth is already working.
3. Only then consider enabling `BatchMode yes` in `~/.ssh/config`.

Example SSH config shape:

```sshconfig
Host your-frp-host
    HostName <host-or-ip>
    User <user>
    IdentityFile ~/.ssh/id_ed25519
    # Add BatchMode yes only after manual SSH testing succeeds
    # BatchMode yes
```

## Test fixtures

Repository fixtures now live under `tests/fixtures/instances/`. They exist for tests and development reference only. Daily usage should start from `frpdeck init ...`, not by editing fixture directories directly.

## Notes on paths

- Relative paths in YAML are resolved against the instance directory, not the shell working directory.
- Rendered systemd units always use absolute runtime paths.
- By default, runtime files are installed under `runtime/` inside the instance directory, while the systemd unit is written to `/etc/systemd/system`.
- FRP's own logs are controlled by `client.log` or `server.log` and are written into generated frpc/frps config.
- `frpdeck`'s own logs are configured by top-level `frpdeck_logging` inside `node.yaml`.
- Source configuration remains YAML. `node.yaml` is always present, while `proxies.yaml` is used for client proxy definitions and may be absent on server instances. There is no separate runtime config file for frpdeck in the current design.
