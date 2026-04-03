# Configuration

## Current Model

`frpdeck` now uses a single instance-centric configuration model.

- Instance source config remains YAML: `node.yaml` is required for every instance, and `proxies.yaml` is used for client proxy definitions
- There is no separate frpdeck runtime config file
- Current config changes are not forward-compatible by policy in this phase

## Instance Config Shape

Top-level `node.yaml` fields:

- `instance_name`
- `role`
- `paths`
- `binary`
- `service`
- `frpdeck_logging`
- `client` or `server`

For server instances, `server.vhost_http_port`, `server.vhost_https_port`, and `server.subdomain_host` are optional and default to unset.

`paths` contains only:

- `install_dir`
- `config_root`
- `systemd_unit_dir`

Removed fields:

- `paths.log_dir`
- `paths.runtime_dir`
- runtime-config `config_version`

## `instance_name`

`instance_name` is the logical identity of the instance.

- It may differ from the directory name
- Status and audit payloads should surface `instance_name`
- Scaffold defaults use it to derive an initial `service.service_name`
- Do not infer identity from `instance_dir.name`

## Logging Semantics

There are two different logging domains:

### FRP logging

`client.log` and `server.log` configure FRP itself.

- They are rendered into frpc/frps TOML
- Their file targets come from `client.log.to` or `server.log.to`
- There is no duplicate top-level `paths.log_dir`

### frpdeck logging

Top-level `frpdeck_logging` configures frpdeck itself.

Fields:

- `level`
- `format`
- `file_path`
- `retention_days`
- `stream`

Behavior:

- Only used when an instance context is available
- `frpdeck_logging.level` uses Python logging's formal level names
- Allowed `stream` values are `stderr`, `stdout`, and `none`
- Operational defaults set `frpdeck_logging.stream` to `stderr`
- With an instance context, logging initialization is fail-fast: invalid instance logging config or missing instance config aborts the operation instead of silently degrading
- File logging uses frpdeck's local daily symlink handler
- Default instance-local file path is `state/logs/frpdeck.log`

Without an instance context, frpdeck falls back to simple process logging on `stderr` and does not require file logging.

## frpdeck Log Level Values

`frpdeck_logging.level` is separate from FRP's own `log.level`.

Allowed values are the Python logging primary names:

- `CRITICAL`
- `ERROR`
- `WARNING`
- `INFO`
- `DEBUG`
- `NOTSET`

At runtime, frpdeck first loads instance logging config from `node.yaml`, resolves paths and enum values into an apply-ready runtime logging config, and only then applies that config to the root logger.

## Defaults

Defaults are split into two categories.

### Operational defaults

Used for normal load/merge/validate:

- `config_defaults/node_client.json`
- `config_defaults/node_server.json`
- `config_defaults/proxy_file.json`

These provide real operational defaults and should not contain scaffold-only placeholders or sample proxy content.

For server instances, the operational defaults leave vhost handling disabled:

- `server.vhost_http_port: null`
- `server.vhost_https_port: null`
- `server.subdomain_host` omitted unless the user sets it explicitly

### Scaffold overrides

Used only by `frpdeck init`:

- `config_defaults/scaffold_client_overrides.json`
- `config_defaults/scaffold_server_overrides.json`
- `config_defaults/scaffold_proxy_file_overrides.json`
- `config_defaults/scaffold_instance_layout.json`
- `config_defaults/scaffold_token_example.json`

Scaffold config is assembled as:

1. load operational defaults
2. load scaffold overrides
3. deep-merge them
4. inject the small amount of instance-specific context needed by `init`

The override files should contain only values that differ from operational defaults. Typical scaffold-only content includes:

- placeholder addresses and domains
- sample client proxies

Current scaffold behavior:

- `frpdeck init server ...` creates `node.yaml` and does not create `proxies.yaml`
- `frpdeck init client ...` creates both `node.yaml` and `proxies.yaml`
- client scaffold includes one sample `http` proxy using `custom_domains`

`config_defaults/scaffold_instance_layout.json` defines the instance directory skeleton created by `frpdeck init`.

`config_defaults/scaffold_token_example.json` remains a separate non-merge resource because it is example text payload, not part of the node/proxy config tree.

`services/scaffold.py` should read these resources and inject only minimal context such as `instance_name`, `role`, derived `service_name`, and client `user`.

## Command Semantics

Operational commands intentionally split source validation, rendered output, runtime sync, and reload/apply behavior:

- `validate` checks source config only and does not write `rendered/` or `runtime/config`
- `render` writes the formal generated snapshot into `rendered/` only
- `sync` mirrors the managed snapshot from `rendered/` into `runtime/config` only
- `reload` acts on the current `runtime/config` for client instances
- `apply` runs the full workflow: validate, render, sync, install/upgrade as needed, install the unit, restart service

`proxy preview` stays separate from top-level `render`:

- `proxy preview` is a temporary client-side proxy include preview and does not mutate `rendered/`
- `render` is the persistent instance render and updates the full `rendered/` tree

## Load Path

Operational instance loading uses merge-before-validate:

1. Read YAML override from disk
2. Detect node role from raw YAML
3. Load package JSON defaults for that role
4. Deep-merge defaults with YAML override
5. Validate with Pydantic models

When present, `proxies.yaml` follows the same pattern with `proxy_file.json`.

## Server Vhost Behavior

Server vhost fields are presence-based, not toggle-based.

- If `server.vhost_http_port` is unset, `frpdeck` does not render `vhostHTTPPort`
- If `server.vhost_https_port` is unset, `frpdeck` does not render `vhostHTTPSPort`
- If `server.subdomain_host` is unset, `frpdeck` does not render `subDomainHost`
- If any of those fields are explicitly set, the rendered `frps.toml` includes them

This keeps the default server scaffold in a plain FRP server mode that does not implicitly claim `80` or `443`.

## HTTP/HTTPS Proxy Route Rules

`http` and `https` proxy entries in `proxies.yaml` support:

- `custom_domains`
- `subdomain`

Rules:

- At least one of `custom_domains` or `subdomain` must be set
- `custom_domains` and `subdomain` may both be set on the same proxy
- Blank or whitespace-only values are rejected for `custom_domains` entries and `subdomain`

Example with `custom_domains`:

```yaml
proxies:
  - name: app_http
    type: http
    local_port: 8080
    custom_domains:
      - app.example.com
```

Example with `subdomain`:

```yaml
proxies:
  - name: app_subdomain
    type: http
    local_port: 8080
    subdomain: app
```

Example with both:

```yaml
proxies:
  - name: app_both
    type: https
    local_port: 8443
    custom_domains:
      - secure.example.com
    subdomain: app
```

## FRP Log Level Values

`client.log.level` and `server.log.level` map directly to FRP's native lowercase values and are validated as a constrained set:

- `trace`
- `debug`
- `info`
- `warn`
- `error`

## Path Resolution

Relative paths are resolved against the instance directory.

This applies to:

- `paths.*`
- FRP token files
- FRP log targets
- `frpdeck_logging.file_path`

Operational code should resolve paths explicitly at runtime, not during raw config loading.

## Binary Source Selection

When FRP binaries need to be installed or replaced, frpdeck uses the following sources:

- `apply --archive /path/to/frp_*.tar.gz` or `upgrade --archive /path/to/frp_*.tar.gz`
- `binary.local_archive` from `node.yaml`
- GitHub release download based on `binary.*`

`apply` and `upgrade` surface download-stage progress in human-readable text mode. Download failures remain fatal and are reported through the existing CLI error path; there is no retry or compatibility fallback layer in the current design.

## Logging Responsibilities

Logging setup is split into two explicit stages:

1. load instance logging config from instance data and resolve it into runtime values
2. apply an already-resolved logging config to the process logger

This keeps config loading separate from root-logger mutation and makes fail-fast behavior easier to reason about.

## Packaging Note

`src/frpdeck/config_defaults/**/*.json` are runtime-critical package resources.

- They are loaded through package resource APIs, not by reaching into the source tree directly.
- Wheel/sdist packaging must include them together with the Jinja templates.
- `config_defaults/` currently stays flat by design:
  - operational defaults: `node_*.json`, `proxy_file.json`
  - scaffold overrides: `scaffold_*_overrides.json`
  - scaffold assets: `scaffold_instance_layout.json`, `scaffold_token_example.json`
