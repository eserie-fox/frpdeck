from pathlib import Path

import pytest

from frpdeck.domain.errors import CommandExecutionError
from frpdeck.services.runtime import run_command


def test_run_command_wraps_missing_command() -> None:
    with pytest.raises(CommandExecutionError) as exc_info:
        run_command(["definitely-not-a-real-command-frpdeck-test"])

    assert "command not found while executing" in str(exc_info.value)
