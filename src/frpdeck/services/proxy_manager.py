"""Structured local proxy management service."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

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
from frpdeck.services.audit import build_actor, new_event_id, read_text_snapshot, record_audit_event, revision_dir_path, write_proxy_revision, yaml_text, utc_timestamp
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

    def update_proxy(self, instance_dir: Path, name: str, patch_spec: ProxyUpdatePatch | dict[str, object]) -> ProxyMutationResult:
        with instance_lock(self._lock_path(instance_dir)):
            instance = instance_dir.resolve()
            proxy_file = self._load_proxy_file(instance)
            index, current = self._find_proxy_with_index(proxy_file, name)
            before_state = self._proxy_audit_state(proxy_file, proxy_name=name)
            before_text = self._proxy_snapshot_text(instance, proxy_file=proxy_file)
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
        instance = instance_dir.resolve()
        lock_path = instance / "state" / ".frpdeck.lock"
        with instance_lock(lock_path):
            proxy_file = self._load_proxy_file(instance)
            before = self._apply_audit_state(proxy_file, reload=reload)
            try:
                node = load_node_config(instance)
                if node.role != Role.CLIENT:
                    raise UnsupportedOperationError("structured proxy apply is only supported for client instances")
                assert isinstance(node, ClientNodeConfig)

                validation = self.validate_proxy_set(instance)
                if validation.errors:
                    report = ApplyReport(
                        ok=False,
                        step="validate",
                        errors=validation.errors,
                        warnings=validation.warnings,
                        reload_requested=reload,
                    )
                    self._attach_apply_audit(instance, before=before, report=report)
                    return report

                try:
                    summary = render_instance(instance, node, proxy_file)
                except Exception as exc:
                    raise ProxyApplyError(f"failed during render: {exc}") from exc

                try:
                    sync_rendered_to_runtime(instance, node)
                except Exception as exc:
                    raise ProxyApplyError(f"failed during runtime sync: {exc}") from exc

                reload_output = None
                reloaded = False
                if reload:
                    try:
                        reload_output = self._reload_client(instance, node)
                        reloaded = True
                    except (CommandExecutionError, ProxyApplyError) as exc:
                        raise ProxyApplyError(f"failed during reload: {exc}") from exc

                report = ApplyReport(
                    ok=True,
                    step="reload" if reload else "render",
                    warnings=validation.warnings,
                    rendered_proxy_files=[path.name for path in summary.rendered_proxy_paths],
                    reload_requested=reload,
                    reloaded=reloaded,
                    reload_output=reload_output,
                )
                self._attach_apply_audit(instance, before=before, report=report)
                return report
            except Exception as exc:
                warning = self._record_apply_failure(instance, before=before, reload=reload, exc=exc)
                if warning:
                    raise type(exc)(f"{exc}; {warning}") from exc
                raise

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

    def _proxy_audit_state(self, proxy_file: ProxyFile, *, proxy_name: str | None = None, fallback_proxy: ProxyConfig | None = None) -> dict[str, Any]:
        proxy_payload = None
        if proxy_name is not None:
            proxy_payload = next((self._serialize_proxy(proxy) for proxy in proxy_file.proxies if proxy.name == proxy_name), None)
        if proxy_payload is None and fallback_proxy is not None:
            proxy_payload = self._serialize_proxy(fallback_proxy)
        return {
            "proxy_count": len(proxy_file.proxies),
            "proxy_names": [proxy.name for proxy in proxy_file.proxies],
            "proxy": proxy_payload,
        }

    def _apply_audit_state(self, proxy_file: ProxyFile, *, reload: bool) -> dict[str, Any]:
        enabled = [proxy.name for proxy in proxy_file.proxies if proxy.enabled]
        return {
            "proxy_count": len(proxy_file.proxies),
            "enabled_proxies": enabled,
            "reload_requested": reload,
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

    def _audit_error_code(self, exc: Exception) -> str:
        if isinstance(exc, ProxyNotFoundError):
            return "proxy_not_found"
        if isinstance(exc, ProxyAlreadyExistsError):
            return "proxy_already_exists"
        if isinstance(exc, ProxyConflictError):
            return "proxy_conflict"
        if isinstance(exc, ProxyApplyError):
            return "apply_failed"
        if isinstance(exc, UnsupportedOperationError):
            return "unsupported_role"
        if isinstance(exc, ConfigLoadError):
            return "config_load_failed"
        if isinstance(exc, CommandExecutionError):
            return "command_execution_failed"
        return "internal_error"

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
                target=target,
                before=before,
                after=after,
                result=audit_result,
                actor=actor,
                ts=ts,
                event_id=event_id,
            )
        except Exception as exc:
            warning = f"audit log append failed: {exc}" if warning is None else f"{warning}; audit log append failed: {exc}"
        if warning is not None:
            result.warnings.append(warning)

    def _attach_apply_audit(self, instance_dir: Path, *, before: dict[str, Any], report: ApplyReport) -> None:
        warning = self._record_apply_audit(
            instance_dir,
            before=before,
            after={
                "step": report.step,
                "rendered_files": list(report.rendered_proxy_files),
                "reload_requested": report.reload_requested,
                "reloaded": report.reloaded,
            },
            result=self._audit_result_payload(
                ok=report.ok,
                error_code=None if report.ok else ("validation_failed" if report.step == "validate" else "apply_failed"),
                errors=report.errors,
                warnings=report.warnings,
                reload_requested=report.reload_requested,
                reloaded=report.reloaded,
                step=report.step,
            ),
        )
        if warning is not None:
            report.warnings.append(warning)

    def _record_apply_failure(self, instance_dir: Path, *, before: dict[str, Any], reload: bool, exc: Exception) -> str | None:
        return self._record_apply_audit(
            instance_dir,
            before=before,
            after={"reload_requested": reload},
            result=self._audit_result_payload(
                ok=False,
                error_code=self._audit_error_code(exc),
                errors=[str(exc)],
                warnings=[],
                reload_requested=reload,
            ),
        )

    def _record_apply_audit(self, instance_dir: Path, *, before: dict[str, Any], after: dict[str, Any], result: dict[str, Any]) -> str | None:
        try:
            record_audit_event(
                instance_dir,
                operation="proxy_apply",
                target={"reload_requested": before.get("reload_requested")},
                before=before,
                after=after,
                result=result,
            )
        except Exception as exc:
            return f"audit log append failed: {exc}"
        return None

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