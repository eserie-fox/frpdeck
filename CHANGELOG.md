# Changelog

All notable changes to this project will be documented in this file.

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