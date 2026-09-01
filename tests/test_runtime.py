import errno

import pytest

from frpdeck.domain.errors import CommandExecutionError
from frpdeck.services.runtime import run_command


def test_run_command_wraps_missing_command(monkeypatch) -> None:
    command = "frpdeck-test-missing-command"

    def raise_missing_command(*args, **kwargs) -> None:
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", command)

    monkeypatch.setattr("frpdeck.services.runtime.subprocess.run", raise_missing_command)

    with pytest.raises(CommandExecutionError) as exc_info:
        run_command([command, "--version"])

    message = str(exc_info.value)
    assert "command not found while executing" in message
    assert f"{command} --version" in message


def test_run_command_wraps_other_os_errors(monkeypatch) -> None:
    command = "frpdeck-test-permission-denied"

    def raise_permission_error(*args, **kwargs) -> None:
        raise PermissionError(errno.EACCES, "Permission denied", command)

    monkeypatch.setattr("frpdeck.services.runtime.subprocess.run", raise_permission_error)

    with pytest.raises(CommandExecutionError) as exc_info:
        run_command([command, "--version"])

    message = str(exc_info.value)
    assert "failed to execute command" in message
    assert f"{command} --version" in message
