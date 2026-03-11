"""Read-only instance status aggregation service."""

from __future__ import annotations

import json
import re
from pathlib import Path

from frpdeck.domain.enums import ProxyType, Role
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError
from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyConfig, ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.state import ClientNodeConfig, NodeBase
from frpdeck.domain.status_models import (
    ClientRuntimeStatus,
    ConfigSummary,
    InstanceStatus,
    LastApplyStatus,
    ProxyCounts,
    ProxyRuntimeStatus,
    RenderSummaryStatus,
    ServiceRuntimeStatus,
)
from frpdeck.services.installer import read_current_version
from frpdeck.services.runtime import run_command
from frpdeck.services.systemd_manager import status_service
from frpdeck.storage.load import load_node_config, load_proxy_file


class StatusService:
    """Aggregate instance state for CLI, web, or MCP-style readers."""

    def get_instance_status(self, instance_dir: Path) -> InstanceStatus:
        instance = instance_dir.resolve()
        warnings: list[str] = []
        errors: list[str] = []
        node: NodeBase | None = None
        proxy_file = ProxyFile()
        node_loaded = False
        proxy_loaded = False

        try:
            node = load_node_config(instance)
            node_loaded = True
        except ConfigLoadError as exc:
            errors.append(str(exc))

        try:
            proxy_file = load_proxy_file(instance)
            proxy_loaded = True
        except ConfigLoadError as exc:
            errors.append(str(exc))

        enabled_proxies = [proxy for proxy in proxy_file.proxies if proxy.enabled]
        config_summary = ConfigSummary(
            node_config_loaded=node_loaded,
            proxy_config_loaded=proxy_loaded,
            proxy_total=len(proxy_file.proxies),
            enabled_proxies=len(enabled_proxies),
            disabled_proxies=len(proxy_file.proxies) - len(enabled_proxies),
        )
        proxy_counts = self._build_proxy_counts(proxy_file)

        current_version = read_current_version(instance)
        if current_version is None:
            warnings.append("current version not available")

        render_summary = self._build_render_summary(instance, node, enabled_proxies)
        last_apply = self._read_last_apply(instance, warnings)
        service_runtime_status = self._read_service_status(node, warnings)
        client_runtime_status = self._read_client_runtime_status(instance, node, warnings)

        return InstanceStatus(
            instance=str(instance),
            instance_name=node.instance_name if node else None,
            role=node.role.value if node else None,
            service_name=node.service.service_name if node else None,
            config_summary=config_summary,
            proxy_counts=proxy_counts,
            current_version=current_version,
            last_apply=last_apply,
            render_summary=render_summary,
            service_status=service_runtime_status,
            client_runtime_status=client_runtime_status,
            warnings=warnings,
            errors=errors,
        )

    def get_proxy_runtime_status(self, instance_dir: Path) -> list[ProxyRuntimeStatus]:
        instance = instance_dir.resolve()
        node: NodeBase | None = None
        try:
            node = load_node_config(instance)
        except ConfigLoadError:
            node = None
        proxy_file = load_proxy_file(instance)
        runtime_output = self._runtime_output(instance, node)
        rendered_root = instance / "rendered" / "proxies.d"

        statuses: list[ProxyRuntimeStatus] = []
        for proxy in proxy_file.proxies:
            rendered_path = rendered_root / f"{self._slugify(proxy.name)}.toml"
            included = rendered_path.exists()
            runtime_present = None if runtime_output is None else proxy.name in runtime_output
            notes: list[str] = []
            if not proxy.enabled:
                notes.append("disabled so not rendered")
            elif not included:
                notes.append("enabled but rendered file is missing")
            if runtime_present is False:
                notes.append("not present in current runtime status")
            if runtime_present is None:
                notes.append("runtime status unavailable")
            statuses.append(
                ProxyRuntimeStatus(
                    name=proxy.name,
                    enabled=proxy.enabled,
                    type=proxy.type.value,
                    description=proxy.description,
                    configured_target=self._configured_target(proxy),
                    rendered_file=str(rendered_path),
                    included_in_current_render=included,
                    runtime_present=runtime_present,
                    notes=notes,
                )
            )
        return statuses

    def _build_proxy_counts(self, proxy_file: ProxyFile) -> ProxyCounts:
        counts = ProxyCounts(total=len(proxy_file.proxies))
        counts.enabled = sum(1 for proxy in proxy_file.proxies if proxy.enabled)
        counts.disabled = counts.total - counts.enabled
        by_type = {proxy_type.value: 0 for proxy_type in ProxyType}
        for proxy in proxy_file.proxies:
            by_type[proxy.type.value] += 1
        counts.by_type = by_type
        return counts

    def _build_render_summary(self, instance: Path, node: NodeBase | None, enabled_proxies: list[ProxyConfig]) -> RenderSummaryStatus:
        rendered_root = instance / "rendered"
        if node is None:
            main_config_exists = (rendered_root / "frpc.toml").exists() or (rendered_root / "frps.toml").exists()
        else:
            main_name = "frpc.toml" if node.role == Role.CLIENT else "frps.toml"
            main_config_exists = (rendered_root / main_name).exists()
        rendered_proxy_files = sorted(path.name for path in (rendered_root / "proxies.d").glob("*.toml")) if (rendered_root / "proxies.d").exists() else []
        matches_enabled = None if node is not None and node.role == Role.SERVER else len(rendered_proxy_files) == len(enabled_proxies)
        return RenderSummaryStatus(
            main_config_exists=main_config_exists,
            rendered_proxy_files=rendered_proxy_files,
            rendered_proxy_count=len(rendered_proxy_files),
            matches_enabled_proxy_count=matches_enabled,
        )

    def _read_last_apply(self, instance: Path, warnings: list[str]) -> LastApplyStatus | None:
        path = instance / "state" / "last_apply.json"
        if not path.exists():
            warnings.append("last apply state not available")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"failed to read last apply state: {exc}")
            return None
        if not isinstance(payload, dict):
            warnings.append("failed to read last apply state: expected JSON object")
            return None
        return LastApplyStatus(
            applied_at=payload.get("applied_at"),
            service_name=payload.get("service_name"),
            config_path=payload.get("config_path"),
        )

    def _read_service_status(self, node: NodeBase | None, warnings: list[str]) -> ServiceRuntimeStatus:
        if node is None:
            return ServiceRuntimeStatus(available=False, note="node config unavailable")
        try:
            raw_output = status_service(node.service.service_name)
        except CommandExecutionError as exc:
            warnings.append(f"service status unavailable: {exc}")
            return ServiceRuntimeStatus(available=False, note=str(exc))
        return ServiceRuntimeStatus(
            available=True,
            active=self._parse_systemd_active(raw_output),
            raw_output=raw_output,
        )

    def _read_client_runtime_status(self, instance: Path, node: NodeBase | None, warnings: list[str]) -> ClientRuntimeStatus | None:
        if node is None or node.role != Role.CLIENT:
            return None
        assert isinstance(node, ClientNodeConfig)
        paths = node.resolved_paths(instance)
        if not paths.binary_path(node.role).exists():
            warnings.append(f"frpc binary not found at {paths.binary_path(node.role)}")
            return ClientRuntimeStatus(available=False, note=f"frpc binary not found at {paths.binary_path(node.role)}")
        if not paths.config_path(node.role).exists():
            warnings.append(f"runtime config not found at {paths.config_path(node.role)}")
            return ClientRuntimeStatus(available=False, note=f"runtime config not found at {paths.config_path(node.role)}")
        try:
            result = run_command(
                [str(paths.binary_path(node.role)), "status", "-c", str(paths.config_path(node.role))],
                check=False,
            )
        except CommandExecutionError as exc:
            warnings.append(f"client runtime status unavailable: {exc}")
            return ClientRuntimeStatus(available=False, note=str(exc))
        raw_output = result.stdout or result.stderr or "frpc status returned no output"
        note = None if result.returncode == 0 else f"frpc status exited with code {result.returncode}"
        if note:
            warnings.append(note)
        return ClientRuntimeStatus(available=result.returncode == 0, raw_output=raw_output, note=note)

    def _runtime_output(self, instance: Path, node: NodeBase | None) -> str | None:
        runtime_status = self._read_client_runtime_status(instance, node, [])
        if runtime_status is None:
            return None
        return runtime_status.raw_output

    def _parse_systemd_active(self, raw_output: str) -> bool | None:
        match = re.search(r"Active:\s+(active|inactive|failed|activating|deactivating)", raw_output)
        if not match:
            return None
        return match.group(1) == "active"

    def _configured_target(self, proxy: ProxyConfig) -> str:
        local_target = f"{proxy.local_ip}:{proxy.local_port}"
        if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)):
            return local_target
        remote_bits: list[str] = []
        if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)):
            if proxy.custom_domains:
                remote_bits.append("domains=" + ",".join(proxy.custom_domains))
            if proxy.subdomain:
                remote_bits.append(f"subdomain={proxy.subdomain}")
        return local_target if not remote_bits else f"{local_target} ({'; '.join(remote_bits)})"

    def _slugify(self, name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "proxy"