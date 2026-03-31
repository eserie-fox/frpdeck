# Changelog

All notable changes to this project will be documented in this file.

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
