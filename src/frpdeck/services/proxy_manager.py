"""Structured local proxy management service."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from frpdeck.domain.enums import ProxyType, Role
from frpdeck.domain.errors import (
    ConfigLoadError,
    ProxyAlreadyExistsError,
    ProxyConflictError,
    ProxyNotFoundError,
    UnsupportedOperationError,
)
from frpdeck.domain.proxy import (
    PROXY_ADAPTER,
    HttpProxyConfig,
    HttpsProxyConfig,
    ProxyConfig,
    ProxyFile,
    TcpProxyConfig,
    UdpProxyConfig,
    validate_http_proxy_routes,
)
from frpdeck.domain.proxy_management import PreviewReport, ProxyMutationResult, ProxyUpdatePatch, ValidationReport
from frpdeck.services.audit import (
    build_actor,
    new_event_id,
    read_text_snapshot,
    record_audit_event,
    revision_dir_path,
    write_proxy_revision,
    yaml_text,
    utc_timestamp,
)
from frpdeck.services.privilege import can_read_path, can_write_file, root_owned_hint
from frpdeck.services.renderer import render_instance
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
            instance = instance_dir.resolve()
            proxy_file = self._load_proxy_file(instance)
            before_state = self._proxy_audit_state(proxy_file, proxy_name=None)
            before_text = self._proxy_snapshot_text(instance, proxy_file=proxy_file)
            proxy = self._validate_proxy_spec(proxy_spec)
            if any(existing.name == proxy.name for existing in proxy_file.proxies):
                raise ProxyAlreadyExistsError(f"proxy already exists: {proxy.name}")
            proxy_file.proxies.append(proxy)
            self._write_proxy_file(instance, proxy_file)
            result = ProxyMutationResult(
                operation="add",
                changed=True,
                proxy=proxy,
                message=f"proxy '{proxy.name}' written to proxies.yaml; apply required",
            )
            self._attach_proxy_audit(
                instance,
                operation="proxy_add",
                target={"proxy_name": proxy.name},
                before=before_state,
                after=self._proxy_audit_state(proxy_file, proxy_name=proxy.name),
                before_yaml=before_text,
                after_yaml=self._proxy_snapshot_text(instance),
                result=result,
            )
            return result

    def import_proxy_file(self, instance_dir: Path, file_path: Path) -> ProxyMutationResult:
        """Import one proxy definition from a YAML file."""
        return self.add_proxy(instance_dir, load_proxy_spec_from_file(file_path.resolve()))

    def update_proxy(
        self, instance_dir: Path, name: str, patch_spec: ProxyUpdatePatch | dict[str, object]
    ) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            instance = instance_dir.resolve()
            proxy_file = self._load_proxy_file(instance)
            index, current = self._find_proxy_with_index(proxy_file, name)
            before_state = self._proxy_audit_state(proxy_file, proxy_name=name)
            before_text = self._proxy_snapshot_text(instance, proxy_file=proxy_file)
            try:
                patch = (
                    patch_spec
                    if isinstance(patch_spec, ProxyUpdatePatch)
                    else ProxyUpdatePatch.model_validate(patch_spec)
                )
            except ValidationError as exc:
                raise ProxyConflictError(str(exc)) from exc
            merged_payload = self._merge_proxy_patch(current, patch)
            updated = self._validate_proxy_spec(merged_payload)
            if updated.name != name and any(
                existing.name == updated.name for i, existing in enumerate(proxy_file.proxies) if i != index
            ):
                raise ProxyAlreadyExistsError(f"proxy already exists: {updated.name}")
            proxy_file.proxies[index] = updated
            self._write_proxy_file(instance, proxy_file)
            result = ProxyMutationResult(
                operation="update",
                changed=True,
                proxy=updated,
                message=f"proxy '{name}' updated in proxies.yaml; apply required",
            )
            self._attach_proxy_audit(
                instance,
                operation="proxy_update",
                target={"proxy_name": name},
                before=before_state,
                after=self._proxy_audit_state(proxy_file, proxy_name=updated.name),
                before_yaml=before_text,
                after_yaml=self._proxy_snapshot_text(instance),
                result=result,
            )
            return result

    def remove_proxy(self, instance_dir: Path, name: str, soft: bool = True) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            instance = instance_dir.resolve()
            proxy_file = self._load_proxy_file(instance)
            index, current = self._find_proxy_with_index(proxy_file, name)
            before_state = self._proxy_audit_state(proxy_file, proxy_name=name)
            before_text = self._proxy_snapshot_text(instance, proxy_file=proxy_file)
            if soft:
                if current.enabled:
                    updated = current.model_copy(update={"enabled": False})
                    proxy_file.proxies[index] = updated
                    self._write_proxy_file(instance, proxy_file)
                    result = ProxyMutationResult(
                        operation="remove",
                        changed=True,
                        proxy=updated,
                        removed_name=name,
                        message=f"proxy '{name}' disabled in proxies.yaml; apply required",
                    )
                    self._attach_proxy_audit(
                        instance,
                        operation="proxy_remove",
                        target={"proxy_name": name, "remove_mode": "soft"},
                        before=before_state,
                        after=self._proxy_audit_state(proxy_file, proxy_name=name),
                        before_yaml=before_text,
                        after_yaml=self._proxy_snapshot_text(instance),
                        result=result,
                    )
                    return result
                return ProxyMutationResult(
                    operation="remove",
                    changed=False,
                    proxy=current,
                    removed_name=name,
                    message=f"proxy '{name}' already disabled; apply may still be required",
                )
            del proxy_file.proxies[index]
            self._write_proxy_file(instance, proxy_file)
            result = ProxyMutationResult(
                operation="remove",
                changed=True,
                removed_name=name,
                message=f"proxy '{name}' deleted from proxies.yaml; apply required",
            )
            self._attach_proxy_audit(
                instance,
                operation="proxy_remove",
                target={"proxy_name": name, "remove_mode": "hard"},
                before=before_state,
                after=self._proxy_audit_state(proxy_file, proxy_name=name, fallback_proxy=None),
                before_yaml=before_text,
                after_yaml=self._proxy_snapshot_text(instance),
                result=result,
            )
            return result

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
            if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)):
                try:
                    validate_http_proxy_routes(proxy.custom_domains, proxy.subdomain, scope=f"proxy {proxy.name}")
                except ValueError as exc:
                    errors.append(str(exc))

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

    def _set_enabled(self, instance_dir: Path, name: str, enabled: bool) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            instance = instance_dir.resolve()
            proxy_file = self._load_proxy_file(instance)
            index, current = self._find_proxy_with_index(proxy_file, name)
            before_state = self._proxy_audit_state(proxy_file, proxy_name=name)
            before_text = self._proxy_snapshot_text(instance, proxy_file=proxy_file)
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
            self._write_proxy_file(instance, proxy_file)
            state = "enabled" if enabled else "disabled"
            result = ProxyMutationResult(
                operation=state,
                changed=True,
                proxy=updated,
                message=f"proxy '{name}' {state} in proxies.yaml; apply required",
            )
            self._attach_proxy_audit(
                instance,
                operation="proxy_enable" if enabled else "proxy_disable",
                target={"proxy_name": name, "enabled": enabled},
                before=before_state,
                after=self._proxy_audit_state(proxy_file, proxy_name=name),
                before_yaml=before_text,
                after_yaml=self._proxy_snapshot_text(instance),
                result=result,
            )
            return result

    def _load_proxy_file(self, instance_dir: Path) -> ProxyFile:
        return load_proxy_file(instance_dir)

    def _lock_path(self, instance_dir: Path) -> Path:
        return instance_dir / "state" / ".frpdeck.lock"

    def _write_proxy_file(self, instance_dir: Path, proxy_file: ProxyFile) -> None:
        dump_yaml_model(proxy_file, instance_dir / "proxies.yaml")

    def _proxy_snapshot_text(self, instance_dir: Path, *, proxy_file: ProxyFile | None = None) -> str:
        fallback = proxy_file or ProxyFile()
        return read_text_snapshot(instance_dir / "proxies.yaml", fallback=fallback) or yaml_text(fallback)

    def _proxy_audit_state(
        self, proxy_file: ProxyFile, *, proxy_name: str | None = None, fallback_proxy: ProxyConfig | None = None
    ) -> dict[str, Any]:
        proxy_payload = None
        if proxy_name is not None:
            proxy_payload = next(
                (self._serialize_proxy(proxy) for proxy in proxy_file.proxies if proxy.name == proxy_name), None
            )
        if proxy_payload is None and fallback_proxy is not None:
            proxy_payload = self._serialize_proxy(fallback_proxy)
        return {
            "proxy_count": len(proxy_file.proxies),
            "proxy_names": [proxy.name for proxy in proxy_file.proxies],
            "proxy": proxy_payload,
        }

    def _serialize_proxy(self, proxy: ProxyConfig) -> dict[str, Any]:
        return proxy.model_dump(mode="json", exclude_none=False)

    def _audit_result_payload(
        self,
        *,
        ok: bool,
        error_code: str | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": ok,
            "error_code": error_code,
            "errors": list(errors or []),
            "warnings": list(warnings or []),
        }
        for key, value in details.items():
            if value is not None:
                payload[key] = value
        return payload

    def _attach_proxy_audit(
        self,
        instance_dir: Path,
        *,
        operation: str,
        target: dict[str, Any],
        before: dict[str, Any],
        after: dict[str, Any],
        before_yaml: str,
        after_yaml: str,
        result: ProxyMutationResult,
    ) -> None:
        ts = utc_timestamp()
        event_id = new_event_id()
        actor = build_actor()
        revision_dir = revision_dir_path(instance_dir, ts=ts, operation=operation, event_id=event_id)
        audit_result = self._audit_result_payload(
            ok=True,
            warnings=result.warnings,
            changed=result.changed,
            apply_required=result.apply_required,
            revision_dir=str(revision_dir),
        )
        warning = None
        try:
            write_proxy_revision(
                instance_dir,
                ts=ts,
                event_id=event_id,
                operation=operation,
                actor=actor,
                result=audit_result,
                before_yaml=before_yaml,
                after_yaml=after_yaml,
            )
        except Exception as exc:
            warning = f"audit revision write failed: {exc}"
            audit_result["warnings"] = list(audit_result["warnings"]) + [warning]
        try:
            record_audit_event(
                instance_dir,
                operation=operation,
                instance_name=self._instance_name(instance_dir),
                target=target,
                before=before,
                after=after,
                result=audit_result,
                actor=actor,
                ts=ts,
                event_id=event_id,
            )
        except Exception as exc:
            warning = (
                f"audit log append failed: {exc}" if warning is None else f"{warning}; audit log append failed: {exc}"
            )
        if warning is not None:
            result.warnings.append(warning)

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

    def _instance_name(self, instance_dir: Path) -> str | None:
        try:
            return load_node_config(instance_dir).instance_name
        except ConfigLoadError:
            return None


def load_proxy_spec_from_file(path: Path) -> dict[str, object]:
    """Load a proxy spec or patch document from YAML."""
    payload = load_yaml_file(path)
    return payload


def analyze_proxy_write_root_requirements(instance_dir: Path) -> list[str]:
    """Return the reasons why one proxy mutation requires elevated privileges."""
    instance = instance_dir.resolve()
    lock_path = instance / "state" / ".frpdeck.lock"
    proxies_path = instance / "proxies.yaml"
    reasons: list[str] = []

    if not can_write_file(lock_path):
        reasons.append(f"instance lock path is not writable by current user: {lock_path}{root_owned_hint(lock_path)}")

    if proxies_path.exists() and not can_read_path(proxies_path):
        reasons.append(f"proxy config is not readable by current user: {proxies_path}{root_owned_hint(proxies_path)}")

    if not can_write_file(proxies_path):
        reasons.append(f"proxy config is not writable by current user: {proxies_path}{root_owned_hint(proxies_path)}")

    return reasons
