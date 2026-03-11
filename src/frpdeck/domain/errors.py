"""Custom exception types."""


class FrpdeckError(Exception):
    """Base exception for all frpdeck errors."""


class ConfigLoadError(FrpdeckError):
    """Raised when a config file cannot be loaded."""


class ConfigValidationError(FrpdeckError):
    """Raised when config validation fails."""


class CommandExecutionError(FrpdeckError):
    """Raised when a subprocess returns a non-zero exit code."""


class DownloadError(FrpdeckError):
    """Raised when a download fails."""


class PermissionOperationError(FrpdeckError):
    """Raised when the current user lacks permissions for an operation."""


class ReleaseNotFoundError(FrpdeckError):
    """Raised when no suitable release asset is found."""


class UnsupportedOperationError(FrpdeckError):
    """Raised when a command is not supported for the requested role."""


class ProxyNotFoundError(FrpdeckError):
    """Raised when a proxy does not exist."""


class ProxyAlreadyExistsError(FrpdeckError):
    """Raised when creating a proxy with a duplicate name."""


class ProxyConflictError(FrpdeckError):
    """Raised when proxy state conflicts with existing configuration."""


class ProxyApplyError(FrpdeckError):
    """Raised when proxy changes cannot be applied."""
