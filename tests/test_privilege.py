import pytest

from frpdeck.commands._invocation import CommandInvocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges
from frpdeck.domain.errors import PermissionOperationError


def test_raise_for_missing_privileges_fails_fast_without_sudo(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: False)

    try:
        raise_for_missing_privileges(
            operation="apply",
            reasons=["will manage system service via systemctl"],
            invocation=CommandInvocation(["apply", "--instance", "/tmp/demo"]),
        )
    except PermissionOperationError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected PermissionOperationError")

    assert "apply requires elevated privileges for this instance" in message
    assert "will manage system service via systemctl" in message
    assert "Retry with: frpdeck apply --instance /tmp/demo --sudo" in message


def test_maybe_reexec_with_sudo_reexecs_with_sudo(monkeypatch) -> None:
    captured: list[list[str]] = []

    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("frpdeck.commands._privilege.command_exists", lambda command: True)
    monkeypatch.setattr("frpdeck.commands._privilege._exec_with_sudo", lambda args: captured.append(args))
    monkeypatch.setattr(
        CommandInvocation,
        "sudo_exec_args",
        lambda self: ["sudo", "frpdeck", *self.argv, "--sudo"],
    )

    result = maybe_reexec_with_sudo(
        operation="apply",
        sudo_requested=True,
        invocation=CommandInvocation(["apply", "--instance", "/tmp/demo"]),
    )

    assert result is True
    assert captured == [["sudo", "frpdeck", "apply", "--instance", "/tmp/demo", "--sudo"]]


def test_maybe_reexec_with_sudo_reports_missing_sudo_for_immediate_reexec(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("frpdeck.commands._privilege.command_exists", lambda command: False)

    with pytest.raises(PermissionOperationError) as exc_info:
        maybe_reexec_with_sudo(
            operation="init",
            sudo_requested=True,
            invocation=CommandInvocation(["init", "client", "demo", "--directory", "/tmp"]),
            subject="the target directory",
        )

    message = str(exc_info.value)
    assert "init requires elevated privileges for the target directory." in message
    assert "`--sudo` was requested, but `sudo` is not available in PATH." in message
    assert "Run this command as root instead: frpdeck init client demo --directory /tmp" in message


def test_maybe_reexec_with_sudo_does_not_reexec_when_already_root(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: True)
    monkeypatch.setattr(
        "frpdeck.commands._privilege._exec_with_sudo",
        lambda args: (_ for _ in ()).throw(AssertionError("should not re-exec")),
    )

    result = maybe_reexec_with_sudo(
        operation="apply",
        sudo_requested=True,
        invocation=CommandInvocation(["apply", "--instance", "/tmp/demo"]),
    )

    assert result is False
