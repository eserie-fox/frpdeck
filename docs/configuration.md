# Configuration

## Current Model

`frpdeck` now uses a single instance-centric configuration model.

- Instance config files remain YAML: `node.yaml` and `proxies.yaml`
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
- sample proxies

`config_defaults/scaffold_instance_layout.json` defines the instance directory skeleton created by `frpdeck init`.

`config_defaults/scaffold_token_example.json` remains a separate non-merge resource because it is example text payload, not part of the node/proxy config tree.

`services/scaffold.py` should read these resources and inject only minimal context such as `instance_name`, `role`, derived `service_name`, and client `user`.

## Load Path

Operational instance loading uses merge-before-validate:

1. Read YAML override from disk
2. Detect node role from raw YAML
3. Load package JSON defaults for that role
4. Deep-merge defaults with YAML override
5. Validate with Pydantic models

`proxies.yaml` follows the same pattern with `proxy_file.json`.

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
