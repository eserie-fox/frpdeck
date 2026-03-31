# Architecture

## Layers

`frpdeck` is organized as a small set of explicit layers:

- `commands`: Typer CLI adapters. They parse flags, format user-facing output, and translate errors into CLI exit behavior.
- `mcp`: MCP server wiring, tool/resource registration, MCP serialization, and stdio startup entrypoints.
- `facade`: stable programmatic adapters that expose structured result envelopes for higher-level callers such as MCP.
- `services`: application logic. Rendering, validation, proxy mutation, install/apply, status aggregation, audit, uninstall, and scaffold behavior belong here.
- `storage`: file I/O helpers for YAML/JSON load/dump and instance locking.
- `domain`: Pydantic models, enums, result types, and shared value objects.
- `config`: package-shipped defaults loading, deep merge helpers, and merge-before-validate config assembly.

## Dependency Direction

Preferred dependency direction is:

- `commands` -> `services`, `storage`, `domain`, `logging`
- `mcp` -> `facade`, `services`, `domain`, `logging`
- `facade` -> `services`, `domain`, `logging`
- `services` -> `storage`, `domain`, `config`
- `storage` -> `domain`, `config`
- `config` -> `domain`
- `domain` -> no project-internal layer

Avoid reverse dependencies. In particular:

- `domain` must not depend on `services`, `commands`, `facade`, or `mcp`
- `services` should not depend on `commands` or `mcp`
- `facade` should stay thin and should not absorb business rules that belong in `services`

## Responsibility Boundaries

Business logic should live in `services`.

Typical examples:

- Proxy validation, mutation, audit attachment, render/apply flow: `services`
- CLI text formatting and JSON envelope emission: `commands`
- MCP tool/resource schemas and MCP-mode wiring: `mcp`
- Stable result-shaping for programmatic callers: `facade`
- Schema validation and shared config models: `domain`
- Defaults loading and merge-before-validate config assembly: `config`

## Entry Point Behavior

CLI, MCP, and facade are different adapters over the same service layer:

- CLI is optimized for operators. It can print human-readable text or explicit JSON envelopes.
- MCP is optimized for protocol-safe stdio interaction. It should keep stdout clean and expose only structured tool/resource responses.
- Facade is optimized for in-process callers. It returns stable `FacadeResult` payloads instead of raising raw service exceptions across the boundary.

## Logging

There is no standalone runtime-config subsystem anymore.

- Without an instance context, frpdeck uses minimal process logging only.
- Without an instance context, the default process stream is `stderr`.
- With an instance context, adapters should load instance-level `frpdeck_logging` from `node.yaml`, resolve it into runtime values, then apply it to the logger; broken instance logging config should fail fast instead of silently degrading.
- FRP logging and frpdeck logging are separate concerns and must stay separate in code and documentation.
