"""Shared enums."""

from enum import Enum


class Role(str, Enum):
    CLIENT = "client"
    SERVER = "server"


class ProxyType(str, Enum):
    TCP = "tcp"
    UDP = "udp"
    HTTP = "http"
    HTTPS = "https"


class TransportProtocol(str, Enum):
    TCP = "tcp"
    KCP = "kcp"
    QUIC = "quic"
    WEBSOCKET = "websocket"
    WSS = "wss"


class InstallChannel(str, Enum):
    GITHUB = "github"


class BandwidthLimitMode(str, Enum):
    CLIENT = "client"
    SERVER = "server"


class FrpdeckLogLevel(str, Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    NOTSET = "NOTSET"


class FrpLogLevel(str, Enum):
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
