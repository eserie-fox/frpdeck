"""Top-level node models and state records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from frpdeck.domain.client_config import ClientCommonConfig
from frpdeck.domain.enums import Role
from frpdeck.domain.install import BinaryConfig
from frpdeck.domain.paths import PathConfig, ResolvedPathConfig
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.systemd import ServiceConfig


class NodeBase(BaseModel):
    """Common instance fields."""

    model_config = ConfigDict(extra="forbid")

    instance_name: str
    role: Role
    paths: PathConfig = Field(default_factory=PathConfig)
    binary: BinaryConfig = Field(default_factory=BinaryConfig)
    service: ServiceConfig

    def resolved_paths(self, instance_dir: Path) -> ResolvedPathConfig:
        return self.paths.resolve(instance_dir)


class ClientNodeConfig(NodeBase):
    role: Literal[Role.CLIENT] = Role.CLIENT
    client: ClientCommonConfig


class ServerNodeConfig(NodeBase):
    role: Literal[Role.SERVER] = Role.SERVER
    server: ServerCommonConfig


NodeConfig = Annotated[ClientNodeConfig | ServerNodeConfig, Field(discriminator="role")]
NODE_CONFIG_ADAPTER = TypeAdapter(NodeConfig)


class InstallState(BaseModel):
    installed_at: str
    version: str
    binary_path: str

    @classmethod
    def create(cls, version: str, binary_path: Path) -> "InstallState":
        return cls(
            installed_at=datetime.now(timezone.utc).isoformat(),
            version=version,
            binary_path=str(binary_path),
        )


class ApplyState(BaseModel):
    applied_at: str
    service_name: str
    config_path: str

    @classmethod
    def create(cls, service_name: str, config_path: Path) -> "ApplyState":
        return cls(
            applied_at=datetime.now(timezone.utc).isoformat(),
            service_name=service_name,
            config_path=str(config_path),
        )
