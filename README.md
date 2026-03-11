# frpdeck

`frpdeck` is a lightweight Python 3.11+ CLI for managing FRP instances from structured source files. It focuses on practical single-host operations: initialize instance directories, validate configuration, render runtime files, apply changes locally, inspect state, and maintain structured proxy definitions without introducing a larger control plane.

It is also MCP-friendly. `frpdeck` includes a local stdio MCP thin wrapper so an LLM can assist with structured proxy maintenance against one bound instance directory at a time.

## Highlights

- Lightweight FRP deployment and maintenance workflows for client and server instances.
- Structured proxy management backed by `proxies.yaml`, with preview and apply support.
- Stable JSON outputs for automation and scripting.
- Append-only audit logging and revision snapshots for write operations.
- Local stdio MCP support for LLM-assisted proxy maintenance.

## Installation

Install from source:

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

## Features

- `init` creates a new client or server instance directory.
- `render` generates FRP TOML, proxy includes, and systemd units under `rendered/`.
- `validate` checks schema, placeholder values, token sources, path resolution, and simple proxy conflicts.
- `apply` validates, renders, installs binaries if needed, syncs runtime files, installs the systemd unit, and restarts the service.
- `reload` calls `frpc reload -c ...` for client instances.
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

Edit the generated configuration and secret material:

```bash
${EDITOR:-vi} ./my-client/node.yaml
${EDITOR:-vi} ./my-client/proxies.yaml
mkdir -p ./my-client/secrets
printf 'replace-me\n' > ./my-client/secrets/token.txt
```

Validate the source configuration:

```bash
frpdeck validate --instance ./my-client
```

Render generated files:

```bash
frpdeck render --instance ./my-client
```

Apply an instance to the configured runtime paths:

```bash
sudo frpdeck apply --instance ./my-client
```

Inspect runtime state:

```bash
frpdeck status --instance ./my-client
```

Apply emits stage-by-stage progress in text mode so it is clear when validation, rendering, runtime sync, systemd install, and restart are happening.

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

### Server instance

1. Run `frpdeck init server your-server`.
2. Replace `PLEASE_FILL_DOMAIN` and create `secrets/token.txt`.
3. Run `frpdeck validate --instance ./your-server`.
4. Run `frpdeck render --instance ./your-server`.
5. Run `sudo frpdeck apply --instance ./your-server`.

## MCP

`frpdeck` ships with a local stdio MCP thin wrapper over structured proxy tools and read-only status resources. It is designed to bind to one instance directory at a time and is best used through a generated wrapper script.

Recommended workflow: generate a bound wrapper script with `frpdeck mcp install-stdio-wrapper` and point your MCP client at that script. Prefer the generated wrapper over writing your own unless you have a specific reason to customize startup behavior. The wrapper binds to your chosen instance directory and embeds the Python interpreter detected when the script is created.

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
