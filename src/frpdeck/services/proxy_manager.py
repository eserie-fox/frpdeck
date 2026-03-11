"""Structured local proxy management service."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import ValidationError

from frpdeck.domain.enums import ProxyType, Role
from frpdeck.domain.errors import (
    CommandExecutionError,
    ConfigLoadError,
    ProxyAlreadyExistsError,
    ProxyApplyError,
    ProxyConflictError,
    ProxyNotFoundError,
    UnsupportedOperationError,
)
from frpdeck.domain.proxy import PROXY_ADAPTER, HttpProxyConfig, HttpsProxyConfig, ProxyConfig, ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport, PreviewReport, ProxyMutationResult, ProxyUpdatePatch, ValidationReport
from frpdeck.domain.state import ClientNodeConfig
from frpdeck.services.installer import sync_rendered_to_runtime
from frpdeck.services.renderer import render_instance
from frpdeck.services.runtime import run_command
from frpdeck.storage.dump import dump_yaml_model
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config, load_proxy_file, load_yaml_file


class ProxyManager:
    """Manage client proxy specs stored in proxies.yaml."""

    def list_proxies(self, instance_dir: Path) -> list[ProxyConfig]:
        return list(self._load_proxy_file(instance_dir).proxies)

    def get_proxy(self, instance_dir: Path, name: str) -> ProxyConfig:
        proxy_file = self._load_proxy_file(instance_dir)
        return self._find_proxy(proxy_file, name)

    def add_proxy(self, instance_dir: Path, proxy_spec: ProxyConfig | dict[str, object]) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            proxy_file = self._load_proxy_file(instance_dir)
            proxy = self._validate_proxy_spec(proxy_spec)
            if any(existing.name == proxy.name for existing in proxy_file.proxies):
                raise ProxyAlreadyExistsError(f"proxy already exists: {proxy.name}")
            proxy_file.proxies.append(proxy)
            self._write_proxy_file(instance_dir, proxy_file)
            return ProxyMutationResult(
                operation="add",
                changed=True,
                proxy=proxy,
                message=f"proxy '{proxy.name}' written to proxies.yaml; apply required",
            )

    def update_proxy(self, instance_dir: Path, name: str, patch_spec: ProxyUpdatePatch | dict[str, object]) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            proxy_file = self._load_proxy_file(instance_dir)
            index, current = self._find_proxy_with_index(proxy_file, name)
            try:
                patch = patch_spec if isinstance(patch_spec, ProxyUpdatePatch) else ProxyUpdatePatch.model_validate(patch_spec)
            except ValidationError as exc:
                raise ProxyConflictError(str(exc)) from exc
            merged_payload = self._merge_proxy_patch(current, patch)
            updated = self._validate_proxy_spec(merged_payload)
            if updated.name != name and any(
                existing.name == updated.name for i, existing in enumerate(proxy_file.proxies) if i != index
            ):
                raise ProxyAlreadyExistsError(f"proxy already exists: {updated.name}")
            proxy_file.proxies[index] = updated
            self._write_proxy_file(instance_dir, proxy_file)
            return ProxyMutationResult(
                operation="update",
                changed=True,
                proxy=updated,
                message=f"proxy '{name}' updated in proxies.yaml; apply required",
            )

    def remove_proxy(self, instance_dir: Path, name: str, soft: bool = True) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            proxy_file = self._load_proxy_file(instance_dir)
            index, current = self._find_proxy_with_index(proxy_file, name)
            if soft:
                if current.enabled:
                    updated = current.model_copy(update={"enabled": False})
                    proxy_file.proxies[index] = updated
                    self._write_proxy_file(instance_dir, proxy_file)
                    return ProxyMutationResult(
                        operation="remove",
                        changed=True,
                        proxy=updated,
                        removed_name=name,
                        message=f"proxy '{name}' disabled in proxies.yaml; apply required",
                    )
                return ProxyMutationResult(
                    operation="remove",
                    changed=False,
                    proxy=current,
                    removed_name=name,
                    message=f"proxy '{name}' already disabled; apply may still be required",
                )
            del proxy_file.proxies[index]
            self._write_proxy_file(instance_dir, proxy_file)
            return ProxyMutationResult(
                operation="remove",
                changed=True,
                removed_name=name,
                message=f"proxy '{name}' deleted from proxies.yaml; apply required",
            )

    def enable_proxy(self, instance_dir: Path, name: str) -> ProxyMutationResult:
        return self._set_enabled(instance_dir, name, True)

    def disable_proxy(self, instance_dir: Path, name: str) -> ProxyMutationResult:
        return self._set_enabled(instance_dir, name, False)

    def validate_proxy_set(self, instance_dir: Path) -> ValidationReport:
        proxy_file = self._load_proxy_file(instance_dir)
        errors: list[str] = []
        warnings: list[str] = []
        seen_names: set[str] = set()
        used_remote_ports: dict[ProxyType, dict[int, str]] = {
            ProxyType.TCP: {},
            ProxyType.UDP: {},
        }

        for raw_proxy in proxy_file.proxies:
            try:
                proxy = self._validate_proxy_spec(raw_proxy)
            except ProxyConflictError as exc:
                errors.append(str(exc))
                continue
            if proxy.name in seen_names:
                errors.append(f"duplicate proxy name: {proxy.name}")
            seen_names.add(proxy.name)

            placeholder_errors = self._proxy_placeholder_errors(proxy)
            errors.extend(placeholder_errors)

            if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)):
                existing = used_remote_ports[proxy.type].get(proxy.remote_port)
                if existing and existing != proxy.name:
                    errors.append(
                        f"duplicate {proxy.type.value} remote_port: {proxy.remote_port} used by '{existing}' and '{proxy.name}'"
                    )
                else:
                    used_remote_ports[proxy.type][proxy.remote_port] = proxy.name
            if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) and not proxy.custom_domains and not proxy.subdomain:
                errors.append(f"proxy {proxy.name} requires custom_domains or subdomain")

        return ValidationReport(ok=not errors, errors=errors, warnings=warnings)

    def preview_proxy_changes(self, instance_dir: Path) -> PreviewReport:
        validation = self.validate_proxy_set(instance_dir)
        proxy_file = self._load_proxy_file(instance_dir)
        enabled = [proxy.name for proxy in proxy_file.proxies if proxy.enabled]
        disabled = [proxy.name for proxy in proxy_file.proxies if not proxy.enabled]

        if validation.errors:
            return PreviewReport(
                ok=False,
                errors=validation.errors,
                warnings=validation.warnings,
                enabled_proxies=enabled,
                disabled_proxies=disabled,
            )

        node = load_node_config(instance_dir)
        if node.role != Role.CLIENT:
            raise UnsupportedOperationError("structured proxy preview is only supported for client instances")

        with tempfile.TemporaryDirectory(prefix="frpdeck-proxy-preview-") as temp_dir_name:
            preview_root = Path(temp_dir_name)
            summary = render_instance(instance_dir, node, proxy_file, output_root=preview_root)
            return PreviewReport(
                ok=True,
                errors=[],
                warnings=validation.warnings,
                enabled_proxies=enabled,
                disabled_proxies=disabled,
                rendered_proxy_files=[path.name for path in summary.rendered_proxy_paths],
            )

    def apply_proxy_changes(self, instance_dir: Path, reload: bool = True) -> ApplyReport:
        lock_path = instance_dir / "state" / ".frpdeck.lock"
        with instance_lock(lock_path):
            node = load_node_config(instance_dir)
            if node.role != Role.CLIENT:
                raise UnsupportedOperationError("structured proxy apply is only supported for client instances")
            assert isinstance(node, ClientNodeConfig)

            proxy_file = self._load_proxy_file(instance_dir)
            validation = self.validate_proxy_set(instance_dir)
            if validation.errors:
                return ApplyReport(
                    ok=False,
                    step="validate",
                    errors=validation.errors,
                    warnings=validation.warnings,
                    reload_requested=reload,
                )

            try:
                summary = render_instance(instance_dir, node, proxy_file)
            except Exception as exc:
                raise ProxyApplyError(f"failed during render: {exc}") from exc

            try:
                sync_rendered_to_runtime(instance_dir, node)
            except Exception as exc:
                raise ProxyApplyError(f"failed during runtime sync: {exc}") from exc

            reload_output = None
            reloaded = False
            if reload:
                try:
                    reload_output = self._reload_client(instance_dir, node)
                    reloaded = True
                except (CommandExecutionError, ProxyApplyError) as exc:
                    raise ProxyApplyError(f"failed during reload: {exc}") from exc

            return ApplyReport(
                ok=True,
                step="reload" if reload else "render",
                warnings=validation.warnings,
                rendered_proxy_files=[path.name for path in summary.rendered_proxy_paths],
                reload_requested=reload,
                reloaded=reloaded,
                reload_output=reload_output,
            )

    def _set_enabled(self, instance_dir: Path, name: str, enabled: bool) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            proxy_file = self._load_proxy_file(instance_dir)
            index, current = self._find_proxy_with_index(proxy_file, name)
            if current.enabled == enabled:
                state = "enabled" if enabled else "disabled"
                return ProxyMutationResult(
                    operation=state,
                    changed=False,
                    proxy=current,
                    message=f"proxy '{name}' already {state}",
                )
            updated = current.model_copy(update={"enabled": enabled})
            proxy_file.proxies[index] = updated
            self._write_proxy_file(instance_dir, proxy_file)
            state = "enabled" if enabled else "disabled"
            return ProxyMutationResult(
                operation=state,
                changed=True,
                proxy=updated,
                message=f"proxy '{name}' {state} in proxies.yaml; apply required",
            )

    def _load_proxy_file(self, instance_dir: Path) -> ProxyFile:
        return load_proxy_file(instance_dir)

    def _lock_path(self, instance_dir: Path) -> Path:
        return instance_dir / "state" / ".frpdeck.lock"

    def _write_proxy_file(self, instance_dir: Path, proxy_file: ProxyFile) -> None:
        dump_yaml_model(proxy_file, instance_dir / "proxies.yaml")

    def _find_proxy(self, proxy_file: ProxyFile, name: str) -> ProxyConfig:
        _, proxy = self._find_proxy_with_index(proxy_file, name)
        return proxy

    def _find_proxy_with_index(self, proxy_file: ProxyFile, name: str) -> tuple[int, ProxyConfig]:
        for index, proxy in enumerate(proxy_file.proxies):
            if proxy.name == name:
                return index, proxy
        raise ProxyNotFoundError(f"proxy not found: {name}")

    def _validate_proxy_spec(self, proxy_spec: ProxyConfig | dict[str, object]) -> ProxyConfig:
        try:
            if isinstance(proxy_spec, dict):
                return PROXY_ADAPTER.validate_python(proxy_spec)
            return PROXY_ADAPTER.validate_python(proxy_spec.model_dump(mode="python", exclude_none=False))
        except ValidationError as exc:
            raise ProxyConflictError(str(exc)) from exc

    def _merge_proxy_patch(self, current: ProxyConfig, patch: ProxyUpdatePatch) -> dict[str, object]:
        payload = current.model_dump(mode="python", exclude_none=False)
        patch_payload = patch.model_dump(exclude_none=True)
        transport_patch = patch_payload.pop("transport", None)
        payload.update(patch_payload)
        if transport_patch is not None:
            current_transport = payload.get("transport", {})
            current_transport.update(transport_patch)
            payload["transport"] = current_transport
        return payload

    def _proxy_placeholder_errors(self, proxy: ProxyConfig) -> list[str]:
        errors: list[str] = []
        values_to_check = [proxy.name, proxy.local_ip]
        if proxy.description:
            values_to_check.append(proxy.description)
        if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)):
            values_to_check.extend(proxy.custom_domains)
            if proxy.subdomain:
                values_to_check.append(proxy.subdomain)
        for value in values_to_check:
            if isinstance(value, str) and value.startswith("PLEASE_FILL_"):
                errors.append(f"proxy {proxy.name} contains placeholder value: {value}")
        return errors

    def _reload_client(self, instance_dir: Path, node: ClientNodeConfig) -> str:
        if not node.client.web_server.addr or not node.client.web_server.port:
            raise ProxyApplyError("client.web_server.addr and client.web_server.port are required for reload")
        paths = node.resolved_paths(instance_dir)
        binary_path = paths.binary_path(node.role)
        config_path = paths.config_path(node.role)
        if not binary_path.exists():
            raise ProxyApplyError(f"frpc binary not found: {binary_path}")
        if not config_path.exists():
            raise ProxyApplyError(f"runtime config not found: {config_path}")
        result = run_command([str(binary_path), "reload", "-c", str(config_path)])
        return result.stdout or "reload completed"


def load_proxy_spec_from_file(path: Path) -> dict[str, object]:
    """Load a proxy spec or patch document from YAML."""
    payload = load_yaml_file(path)
    return payload