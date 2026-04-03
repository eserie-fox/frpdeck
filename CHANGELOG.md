# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

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
