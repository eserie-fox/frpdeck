# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

## 1.1.4

- Added `client.web_server.enable`, defaulting to `true`, so client instances can explicitly control whether frpc's web server is rendered.
- When `client.web_server.enable` is `false`, `frpdeck` omits the generated `[webServer]` config even though default `addr` and `port` values still exist after config merge.
- Made `reload` fail fast with a clear error when the client web server is disabled, because `frpc reload` depends on that control endpoint.
- Documented the client web server enable behavior and covered the default, disabled render, config merge, scaffold, and reload paths with tests.
- Added a GitHub Actions CI workflow with separate `format-lint` and `tests` jobs backed by the `dev` extra.
- Split quick-start usage into `QUICKSTART.md` and shortened `README.md` so new users can jump directly to first client/server workflows.
- Kept dependency declarations on lower bounds only and removed tests that depended on unstable Typer/Click internals.
- Ignored local `uv.lock` resolver output and added a `Makefile` with `sync`, format/lint, test, check, and clean targets.

## 1.1.3

- Added consistent full-command `--sudo` re-exec support for mutating workflows, with clearer fail-fast permission errors and retry hints.
- Tightened privilege prechecks and filesystem/config error handling across init, render, sync, restart, upgrade, uninstall, structured proxy mutations, and MCP wrapper operations, with expanded CLI and privilege test coverage.
- Switched package version metadata to load dynamically from `frpdeck.version.__version__` and aligned the release-process documentation around that single version source.
- Removed package-level re-exports and lazy exports in favor of leaf-module imports, and fixed instance log-path resolution so `frpdeck.log` stays pinned to the stable symlink name instead of breaking MCP-bound startup with ever-growing daily log filenames.

## 1.1.2

- Changed server operational defaults and scaffold output so vhost HTTP/HTTPS ports and `subdomain_host` are unset by default; new server instances no longer implicitly bind `80` or `443`.
- Reworked proxy CLI structure around `proxy import <file>`, `proxy update <name> <file>`, and `proxy add tcp|udp|http|https`, and removed the duplicate `proxy validate` / `proxy apply` command layer.
- Added a dedicated top-level `sync` command so `rendered/` to `runtime/config` mirroring is explicit and can safely delete stale managed proxy include files without bundling render, validate, reload, or restart.
- Updated MCP proxy tools to match the new CLI mental model with unified `add_proxy`, file import, CRUD, and preview support; removed MCP proxy-apply/proxy-validate endpoints.
- Tightened HTTP/HTTPS proxy validation across models, proxy writes, docs, and tests so `custom_domains` or `subdomain` is required and blank values are rejected before render.
- Relaxed fragile help-text tests so they keep asserting command content without hard-binding Typer/Click-specific help exit codes.

## 1.1.1

- Fixed the generated MCP stdio wrapper so its default embedded Python interpreter is stable and no longer changes implicitly with `VIRTUAL_ENV`; `--python` remains the explicit override.
- Further reduced MCP tool registration duplication by collapsing bound and generic wrapper generation into a single shape-driven helper path while keeping tool schemas and behavior stable.
- Tightened the 1.1.x cleanup work around machine-readable CLI output, internal apply/proxy/MCP orchestration, and normalized HTTP request headers for release consistency.

## 1.1.0

- Converged configuration further around the instance-centric model, including clearer defaults, scaffold resources, and packaged instance skeleton definitions.
- Clarified the boundary between FRP log settings and `frpdeck`'s own logging, with stricter enum-based modeling and explicit load-versus-apply logging helpers.
- Switched scaffold generation fully to operational-defaults-plus-overrides resources and tightened config resource packaging expectations.
- Improved repository consistency across CLI, MCP, docs, tests, and release metadata in preparation for the 1.1.0 release.

## 1.0.1

- Polished release packaging and metadata for the 1.0.1 patch release.
- Updated the README installation guidance to clearly document `pip install frpdeck` for regular users.
- Aligned version strings and release notes so documentation, package metadata, and release preparation stay consistent.
- Added release-process polish for public publishing readiness, including GitHub Actions and Trusted Publishing preparation.

## 1.0.0

- Initial open-source release of `frpdeck` as a lightweight FRP deployment and maintenance CLI.
- Added instance scaffolding, validation, rendering, apply, restart, status, upgrade, and uninstall workflows for FRP client and server instances.
- Added structured proxy management with typed add, update, enable, disable, remove, preview, and apply operations.
- Added stable JSON outputs for automation-friendly CLI usage.
- Added append-only audit logging and revision snapshots for write operations.
- Added a local stdio MCP thin wrapper for instance-bound proxy maintenance and status inspection.
- Added helper commands for generating and removing MCP stdio wrapper scripts.
