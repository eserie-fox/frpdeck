"""Path models and resolution helpers."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from frpdeck.domain.enums import Role


class PathConfig(BaseModel):
    """Paths that may be relative to the instance directory."""

    model_config = ConfigDict(extra="forbid")

    install_dir: Path = Path("runtime/bin")
    config_root: Path = Path("runtime/config")
    log_dir: Path = Path("runtime/logs")
    runtime_dir: Path = Path("runtime/run")
    systemd_unit_dir: Path = Path("/etc/systemd/system")

    @field_validator("install_dir", "config_root", "log_dir", "runtime_dir", "systemd_unit_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)

    def resolve(self, instance_dir: Path) -> "ResolvedPathConfig":
        """Return an absolute-path version of this config."""
        return ResolvedPathConfig(
            install_dir=_resolve_path(self.install_dir, instance_dir),
            config_root=_resolve_path(self.config_root, instance_dir),
            log_dir=_resolve_path(self.log_dir, instance_dir),
            runtime_dir=_resolve_path(self.runtime_dir, instance_dir),
            systemd_unit_dir=_resolve_path(self.systemd_unit_dir, instance_dir),
        )


class ResolvedPathConfig(PathConfig):
    """Absolute runtime paths."""

    @field_validator("install_dir", "config_root", "log_dir", "runtime_dir", "systemd_unit_dir")
    @classmethod
    def _ensure_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"resolved path must be absolute: {value}")
        return value

    def binary_path(self, role: Role) -> Path:
        return self.install_dir / ("frpc" if role == Role.CLIENT else "frps")

    def config_path(self, role: Role) -> Path:
        return self.config_root / ("frpc.toml" if role == Role.CLIENT else "frps.toml")

    def proxies_dir(self) -> Path:
        return self.config_root / "proxies.d"

    def unit_path(self, service_name: str) -> Path:
        return self.systemd_unit_dir / f"{service_name}.service"


def _resolve_path(raw_path: Path, instance_dir: Path) -> Path:
    if raw_path.is_absolute():
        return raw_path
    return (instance_dir / raw_path).resolve()


def resolve_path_from_instance(raw_path: Path | str, instance_dir: Path) -> Path:
    """Resolve any path against an instance directory."""
    return _resolve_path(Path(raw_path), instance_dir)
