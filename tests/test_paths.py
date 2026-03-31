from pathlib import Path

from frpdeck.domain.paths import PathConfig


def test_relative_paths_resolve_from_instance_dir(tmp_path: Path) -> None:
    config = PathConfig(
        install_dir=Path("bin"),
        config_root=Path("config"),
        systemd_unit_dir=Path("/etc/systemd/system"),
    )

    resolved = config.resolve(tmp_path)

    assert resolved.install_dir == (tmp_path / "bin").resolve()
    assert resolved.config_root == (tmp_path / "config").resolve()
    assert resolved.systemd_unit_dir == Path("/etc/systemd/system")


def test_absolute_paths_are_preserved(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute-bin"
    config = PathConfig(
        install_dir=absolute,
        config_root=Path("config"),
        systemd_unit_dir=Path("/etc/systemd/system"),
    )

    resolved = config.resolve(tmp_path)

    assert resolved.install_dir == absolute
