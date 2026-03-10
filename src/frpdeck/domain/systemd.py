"""systemd unit configuration."""

from pydantic import BaseModel, ConfigDict


class ServiceConfig(BaseModel):
    """systemd unit settings."""

    model_config = ConfigDict(extra="forbid")

    service_name: str
    user: str = "root"
    group: str = "root"
    restart: str = "always"
    restart_sec: int = 2
    wanted_by: str = "multi-user.target"
