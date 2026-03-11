"""Stable proxy facade for programmatic callers."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from frpdeck.domain.errors import (
    CommandExecutionError,
    ConfigLoadError,
    ProxyAlreadyExistsError,
    ProxyApplyError,
    ProxyConflictError,
    ProxyNotFoundError,
    UnsupportedOperationError,
)
from frpdeck.domain.facade_models import FacadeResult
from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyConfig, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport, PreviewReport, ProxyMutationResult, ValidationReport
from frpdeck.services.proxy_manager import ProxyManager


class ProxyFacade:
    """Programmatic adapter around ProxyManager."""

    def __init__(self, manager: ProxyManager | None = None) -> None:
        self._manager = manager or ProxyManager()

    def list_proxies(self, instance_dir: Path) -> FacadeResult:
        operation = "list_proxies"
        instance = instance_dir.resolve()
        try:
            proxies = self._manager.list_proxies(instance)
            return self._success(operation, instance, {"count": len(proxies), "proxies": [self._serialize_proxy(proxy) for proxy in proxies]})
        except Exception as exc:
            return self._error(operation, instance, exc)

    def get_proxy(self, instance_dir: Path, name: str) -> FacadeResult:
        operation = "get_proxy"
        instance = instance_dir.resolve()
        try:
            proxy = self._manager.get_proxy(instance, name)
            return self._success(operation, instance, {"proxy": self._serialize_proxy(proxy)})
        except Exception as exc:
            return self._error(operation, instance, exc)

    def add_proxy(self, instance_dir: Path, proxy_spec: ProxyConfig | dict[str, object]) -> FacadeResult:
        operation = "add_proxy"
        instance = instance_dir.resolve()
        try:
            result = self._manager.add_proxy(instance, proxy_spec)
            return self._success(operation, instance, self._serialize_mutation_result(result), warnings=result.warnings)
        except Exception as exc:
            return self._error(operation, instance, exc)

    def update_proxy(self, instance_dir: Path, name: str, patch_spec: dict[str, object] | BaseModel) -> FacadeResult:
        operation = "update_proxy"
        instance = instance_dir.resolve()
        try:
            result = self._manager.update_proxy(instance, name, patch_spec)
            return self._success(operation, instance, self._serialize_mutation_result(result), warnings=result.warnings)
        except Exception as exc:
            return self._error(operation, instance, exc)

    def remove_proxy(self, instance_dir: Path, name: str, soft: bool = True) -> FacadeResult:
        operation = "remove_proxy"
        instance = instance_dir.resolve()
        try:
            result = self._manager.remove_proxy(instance, name, soft=soft)
            return self._success(operation, instance, self._serialize_mutation_result(result), warnings=result.warnings)
        except Exception as exc:
            return self._error(operation, instance, exc)

    def enable_proxy(self, instance_dir: Path, name: str) -> FacadeResult:
        operation = "enable_proxy"
        instance = instance_dir.resolve()
        try:
            result = self._manager.enable_proxy(instance, name)
            return self._success(operation, instance, self._serialize_mutation_result(result), warnings=result.warnings)
        except Exception as exc:
            return self._error(operation, instance, exc)

    def disable_proxy(self, instance_dir: Path, name: str) -> FacadeResult:
        operation = "disable_proxy"
        instance = instance_dir.resolve()
        try:
            result = self._manager.disable_proxy(instance, name)
            return self._success(operation, instance, self._serialize_mutation_result(result), warnings=result.warnings)
        except Exception as exc:
            return self._error(operation, instance, exc)

    def validate_proxy_set(self, instance_dir: Path) -> FacadeResult:
        operation = "validate_proxy_set"
        instance = instance_dir.resolve()
        try:
            report = self._manager.validate_proxy_set(instance)
            data = self._serialize_validation_report(report)
            if report.ok:
                return self._success(operation, instance, data, warnings=report.warnings)
            return FacadeResult(
                ok=False,
                operation=operation,
                instance=str(instance),
                data=data,
                error_code="validation_failed",
                errors=list(report.errors),
                warnings=list(report.warnings),
            )
        except Exception as exc:
            return self._error(operation, instance, exc)

    def preview_proxy_changes(self, instance_dir: Path) -> FacadeResult:
        operation = "preview_proxy_changes"
        instance = instance_dir.resolve()
        try:
            report = self._manager.preview_proxy_changes(instance)
            data = self._serialize_preview_report(report)
            if report.ok:
                return self._success(operation, instance, data, warnings=report.warnings)
            return FacadeResult(
                ok=False,
                operation=operation,
                instance=str(instance),
                data=data,
                error_code="validation_failed",
                errors=list(report.errors),
                warnings=list(report.warnings),
            )
        except Exception as exc:
            return self._error(operation, instance, exc)

    def apply_proxy_changes(self, instance_dir: Path, reload: bool = True) -> FacadeResult:
        operation = "apply_proxy_changes"
        instance = instance_dir.resolve()
        try:
            applied_proxies = [proxy.name for proxy in self._manager.list_proxies(instance) if proxy.enabled]
            report = self._manager.apply_proxy_changes(instance, reload=reload)
            data = self._serialize_apply_report(report, applied_proxies)
            if report.ok:
                return self._success(operation, instance, data, warnings=report.warnings)
            return FacadeResult(
                ok=False,
                operation=operation,
                instance=str(instance),
                data=data,
                error_code="validation_failed" if report.step == "validate" else "apply_failed",
                errors=list(report.errors),
                warnings=list(report.warnings),
            )
        except Exception as exc:
            return self._error(operation, instance, exc)

    def _success(self, operation: str, instance: Path, data: Any, warnings: list[str] | None = None) -> FacadeResult:
        return FacadeResult(
            ok=True,
            operation=operation,
            instance=str(instance),
            data=self._json_ready(data),
            warnings=list(warnings or []),
        )

    def _error(self, operation: str, instance: Path, exc: Exception) -> FacadeResult:
        error_code = self._error_code(exc)
        return FacadeResult(
            ok=False,
            operation=operation,
            instance=str(instance),
            error_code=error_code,
            errors=[str(exc)],
        )

    def _error_code(self, exc: Exception) -> str:
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

    def _json_ready(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, BaseModel):
            return self._json_ready(value.model_dump(mode="json", exclude_none=False))
        if isinstance(value, dict):
            return {str(key): self._json_ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_ready(item) for item in value]
        raise TypeError(f"unsupported facade serialization type: {type(value).__name__}")

    def _serialize_proxy(self, proxy: ProxyConfig) -> dict[str, Any]:
        return {
            "name": proxy.name,
            "enabled": proxy.enabled,
            "type": proxy.type.value,
            "description": proxy.description,
            "local_ip": proxy.local_ip,
            "local_port": proxy.local_port,
            "remote_port": proxy.remote_port if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)) else None,
            "custom_domains": list(proxy.custom_domains) if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) else [],
            "subdomain": proxy.subdomain if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) else None,
            "annotations": dict(proxy.annotations),
            "metadatas": dict(proxy.metadatas),
            "transport": proxy.transport.model_dump(mode="json", exclude_none=False),
        }

    def _serialize_mutation_result(self, result: ProxyMutationResult) -> dict[str, Any]:
        return {
            "operation": result.operation,
            "changed": result.changed,
            "apply_required": result.apply_required,
            "removed_name": result.removed_name,
            "message": result.message,
            "proxy": self._serialize_proxy(result.proxy) if result.proxy is not None else None,
        }

    def _serialize_validation_report(self, report: ValidationReport) -> dict[str, Any]:
        return {
            "ok": report.ok,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        }

    def _serialize_preview_report(self, report: PreviewReport) -> dict[str, Any]:
        return {
            "valid": report.ok,
            "enabled_proxies": list(report.enabled_proxies),
            "disabled_proxies": list(report.disabled_proxies),
            "rendered_files": list(report.rendered_proxy_files),
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        }

    def _serialize_apply_report(self, report: ApplyReport, applied_proxies: list[str]) -> dict[str, Any]:
        return {
            "success": report.ok,
            "step": report.step,
            "reloaded": report.reloaded,
            "reload_requested": report.reload_requested,
            "reload_output": report.reload_output,
            "rendered_files": list(report.rendered_proxy_files),
            "applied_proxies": list(applied_proxies),
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        }