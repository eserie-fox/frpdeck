from frpdeck.commands._privilege import ensure_root_privileges
from frpdeck.domain.errors import PermissionOperationError


def test_ensure_root_privileges_fails_fast_without_sudo(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: False)

    try:
        ensure_root_privileges(
            operation="apply",
            reasons=["will manage system service via systemctl"],
            sudo_requested=False,
            command_args=["apply", "--instance", "/tmp/demo"],
        )
    except PermissionOperationError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected PermissionOperationError")

    assert "apply requires elevated privileges for this instance" in message
    assert "will manage system service via systemctl" in message
    assert "Retry with: frpdeck apply --instance /tmp/demo --sudo" in message


def test_ensure_root_privileges_reexecs_with_sudo(monkeypatch) -> None:
    captured: list[list[str]] = []

    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("frpdeck.commands._privilege.command_exists", lambda command: True)
    monkeypatch.setattr("frpdeck.commands._privilege._exec_with_sudo", lambda args: captured.append(args))
    monkeypatch.setattr("frpdeck.commands._privilege.Path.exists", lambda self: True)
    monkeypatch.setattr("frpdeck.commands._privilege.os.access", lambda path, mode: True)

    result = ensure_root_privileges(
        operation="apply",
        reasons=["will manage system service via systemctl"],
        sudo_requested=True,
        command_args=["apply", "--instance", "/tmp/demo"],
    )

    assert result is True
    assert captured
    assert captured[0][0] == "sudo"
    assert "--sudo" in captured[0]


def test_ensure_root_privileges_does_not_reexec_when_already_root(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.commands._privilege.current_user_is_root", lambda: True)
    monkeypatch.setattr(
        "frpdeck.commands._privilege._exec_with_sudo",
        lambda args: (_ for _ in ()).throw(AssertionError("should not re-exec")),
    )

    result = ensure_root_privileges(
        operation="apply",
        reasons=["will manage system service via systemctl"],
        sudo_requested=True,
        command_args=["apply", "--instance", "/tmp/demo"],
    )

    assert result is False
