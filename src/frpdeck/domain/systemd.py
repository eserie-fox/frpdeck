"""systemd unit configuration."""

from pydantic import BaseModel, ConfigDict


class ServiceConfig(BaseModel):
    """systemd unit settings."""

    model_config = ConfigDict(extra="forbid")

    service_name: str
    user: str
    group: str
    restart: str
    restart_sec: int
    wanted_by: str
