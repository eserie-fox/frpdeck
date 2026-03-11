# frpdeck

`frpdeck` is a Python 3.11+ CLI for managing FRP client and server deployments from structured YAML source files. This first stage focuses on deployment and maintenance workflows: initialize instance directories, validate configs, render FRP and systemd files, apply them locally, inspect status, and upgrade binaries.

## Current capabilities

- `init` creates a new client or server instance directory.
- `render` generates FRP TOML, proxy includes, and systemd units under `rendered/`.
- `validate` checks schema, placeholder values, token sources, path resolution, and simple proxy conflicts.
- `apply` validates, renders, installs binaries if needed, syncs runtime files, installs the systemd unit, and restarts the service.
- `reload` calls `frpc reload -c ...` for client instances.
- `restart` and `status` operate on the configured systemd service.
- `check-update` and `upgrade` support GitHub latest releases and offline archives.
- `doctor` checks Linux/systemd availability, instance files, and basic write permissions.
- `python -m frpdeck.mcp.server` starts a local stdio MCP server that exposes proxy-management tools and read-only status resources.

## Not implemented yet

- Remote HTTP transport for MCP
- Authentication or authorization for remote MCP access
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

## Client workflow

1. Run `frpdeck init client your-client`.
2. Replace `PLEASE_FILL_SERVER_ADDR` and domain placeholders in `node.yaml` and `proxies.yaml`.
3. Create `secrets/token.txt` with the real token.
4. Run `frpdeck validate --instance ./your-client`.
5. Run `frpdeck render --instance ./your-client`.
6. Run `sudo frpdeck apply --instance ./your-client`.
7. Run `frpdeck status --instance ./your-client`.

## Server workflow

1. Run `frpdeck init server your-server`.
2. Replace `PLEASE_FILL_DOMAIN` and create `secrets/token.txt`.
3. Run `frpdeck validate --instance ./your-server`.
4. Run `frpdeck render --instance ./your-server`.
5. Run `sudo frpdeck apply --instance ./your-server`.

## MCP

The current MCP surface is a thin local stdio wrapper over frpdeck tools and status resources. It binds to one frpdeck instance directory at a time and is best used through a generated wrapper script. It does not provide HTTP transport, remote auth, or a web UI.

Recommended workflow: generate a bound wrapper script with `frpdeck mcp install-stdio-wrapper` and point Claude Code at that script. Prefer the generated wrapper over writing your own script unless you have a specific reason to customize it. The wrapper binds to your chosen instance directory and embeds the Python interpreter that is running `frpdeck` when the script is created.

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
