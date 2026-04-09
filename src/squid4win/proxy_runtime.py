from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
import zlib
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs

import brotli
import httpx
import trustme
from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

from squid4win.logging_utils import get_logger
from squid4win.models import (
    ProxyRuntimeValidationOptions,
    ProxyRuntimeValidationResult,
    RepositoryPaths,
)
from squid4win.paths import resolve_path
from squid4win.utils.actions import append_step_summary

if TYPE_CHECKING:
    from squid4win.runner import PlanRunner


_LOCAL_PAYLOAD_SEED = b"squid4win-proxy-runtime"
_EXTERNAL_H2_ENDPOINT = "https://nghttp2.org/httpbin/get"
_EXTERNAL_HTTP_ENDPOINT = "https://httpbingo.org/get"
_EXTERNAL_TLS12_ENDPOINT = "https://tls-v1-2.badssl.com:1012/"
_EXTERNAL_TLS13_ENDPOINT = "https://tls-v1-3.badssl.com:1013/"
type ValidationOutcome = tuple[list[str], list[str]]


@dataclass(frozen=True)
class ScenarioSample:
    request_id: str
    latency_ms: float
    status_code: int | None
    http_version: str | None
    bytes_received: int
    error: str | None = None


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    description: str
    required: bool
    request_count: int
    success_count: int
    failure_count: int
    min_latency_ms: float | None
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    http_versions: tuple[str, ...]
    request_ids: tuple[str, ...]
    errors: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.failure_count == 0

    def to_json(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "description": self.description,
            "required": self.required,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "min_latency_ms": self.min_latency_ms,
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "http_versions": list(self.http_versions),
            "request_ids": list(self.request_ids),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    description: str
    required: bool
    runner: Callable[[httpx.AsyncClient, httpx.AsyncClient], Awaitable[ScenarioResult]]


@dataclass(frozen=True)
class LocalOrigins:
    cleartext_base_url: str
    tls_http1_base_url: str
    tls_http2_base_url: str


@dataclass
class ManagedProxy:
    proxy_url: str
    config_path: Path
    stdout_log_path: Path
    stderr_log_path: Path
    access_log_path: Path
    cache_log_path: Path
    stdout_handle: Any
    stderr_handle: Any
    process: subprocess.Popen[str]


@dataclass
class RunArtifacts:
    run_root: Path
    summary_path: Path
    json_path: Path
    access_log_tail_path: Path | None = None
    cache_log_tail_path: Path | None = None
    process_stdout_path: Path | None = None
    process_stderr_path: Path | None = None


class LocalOriginApp:
    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            return

        request_body = await self._drain_request_body(receive)
        raw_headers = scope.get("headers", [])
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in raw_headers
        }
        path = str(scope.get("path", ""))
        query_string = scope.get("query_string", b"")
        query = parse_qs(query_string.decode("utf-8"), keep_blank_values=True)
        request_id = self._request_id(query, headers)

        if path.startswith("/redirect/"):
            redirect_count = max(0, _parse_int(path.rsplit("/", 1)[-1], default=0))
            target = (
                f"/bytes/4096?request_id={request_id}"
                if redirect_count <= 0
                else f"/redirect/{redirect_count - 1}?request_id={request_id}"
            )
            await self._send_response(
                send,
                status=302,
                headers=[
                    (b"location", target.encode("utf-8")),
                    (b"x-squid4win-request-id", request_id.encode("utf-8")),
                ],
                body=b"",
            )
            return

        if path == "/drip":
            payload = _deterministic_payload(
                _parse_int(query.get("numbytes", ["32768"])[0], default=32768)
            )
            chunk_count = max(1, _parse_int(query.get("chunks", ["8"])[0], default=8))
            interval_ms = max(0, _parse_int(query.get("interval_ms", ["25"])[0], default=25))
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/octet-stream"),
                        (b"x-squid4win-request-id", request_id.encode("utf-8")),
                        (b"x-squid4win-content-sha256", _sha256_hex(payload).encode("ascii")),
                    ],
                }
            )
            for chunk in _chunk_bytes(payload, chunk_count):
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await asyncio.sleep(interval_ms / 1000)
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        if path in {"/gzip", "/deflate", "/brotli"}:
            encoding = path.removeprefix("/")
            payload = _json_bytes(
                {
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": path,
                    "query": query,
                    "request_body_bytes": len(request_body),
                }
            )
            encoded_payload = _encode_payload(payload, encoding)
            await self._send_response(
                send,
                status=200,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"content-encoding", encoding.encode("ascii")),
                    (b"x-squid4win-request-id", request_id.encode("utf-8")),
                    (b"x-squid4win-encoding", encoding.encode("ascii")),
                    (b"x-squid4win-content-sha256", _sha256_hex(payload).encode("ascii")),
                ],
                body=encoded_payload,
            )
            return

        if path.startswith("/bytes/"):
            payload = _deterministic_payload(
                _parse_int(path.rsplit("/", 1)[-1], default=4096)
            )
            await self._send_response(
                send,
                status=200,
                headers=[
                    (b"content-type", b"application/octet-stream"),
                    (b"x-squid4win-request-id", request_id.encode("utf-8")),
                    (b"x-squid4win-content-sha256", _sha256_hex(payload).encode("ascii")),
                ],
                body=payload,
            )
            return

        if path == "/headers":
            payload = _json_bytes(
                {
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "headers": headers,
                    "http_version": scope.get("http_version"),
                }
            )
            await self._send_response(
                send,
                status=200,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"x-squid4win-request-id", request_id.encode("utf-8")),
                    (b"x-squid4win-content-sha256", _sha256_hex(payload).encode("ascii")),
                ],
                body=payload,
            )
            return

        payload = _json_bytes(
            {
                "request_id": request_id,
                "method": scope.get("method"),
                "path": path,
                "query": query,
                "http_version": scope.get("http_version"),
                "scheme": scope.get("scheme"),
                "request_body_bytes": len(request_body),
            }
        )
        await self._send_response(
            send,
            status=200,
            headers=[
                (b"content-type", b"application/json"),
                (b"x-squid4win-request-id", request_id.encode("utf-8")),
                (b"x-squid4win-content-sha256", _sha256_hex(payload).encode("ascii")),
            ],
            body=payload,
        )

    @staticmethod
    async def _drain_request_body(
        receive: Callable[[], Awaitable[dict[str, Any]]]
    ) -> bytes:
        body_parts: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        return b"".join(body_parts)

    @staticmethod
    def _request_id(query: dict[str, list[str]], headers: dict[str, str]) -> str:
        candidates = query.get("request_id", [])
        if candidates:
            return candidates[0]
        header_value = headers.get("x-squid4win-request-id")
        return header_value if header_value else uuid.uuid4().hex

    @staticmethod
    async def _send_response(
        send: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        status: int,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
    ) -> None:
        final_headers = list(headers)
        final_headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": final_headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


def run_proxy_runtime_validation(
    options: ProxyRuntimeValidationOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    del runner
    logger = get_logger("squid4win")
    paths = RepositoryPaths.discover(options.repository_root)
    run_root = _resolve_run_root(paths, options.artifact_root)
    if not execute:
        logger.info(
            "The Python automation will validate proxy runtime behavior and store "
            "artifacts under '%s'.",
            run_root,
        )
        mode = "managed binary" if options.binary_path is not None else "live proxy"
        logger.info("Validation target: %s.", mode)
        return 0

    result = asyncio.run(_execute_validation(options, paths, run_root))
    logger.info(
        "Proxy runtime validation recorded %d failed scenario(s) across %d scenario(s).",
        result.failed_scenarios,
        result.scenario_count,
    )
    if result.failed_scenarios:
        msg = (
            "Proxy runtime validation found failures. "
            f"See '{result.summary_path}' and '{result.json_path}' for details."
        )
        raise RuntimeError(msg)
    return 0


async def _execute_validation(
    options: ProxyRuntimeValidationOptions,
    paths: RepositoryPaths,
    run_root: Path,
) -> ProxyRuntimeValidationResult:
    logger = get_logger("squid4win")
    run_root.mkdir(parents=True, exist_ok=True)
    artifacts = RunArtifacts(
        run_root=run_root,
        summary_path=run_root / "summary.md",
        json_path=run_root / "summary.json",
    )
    install_root = _resolve_install_root(options, paths)
    log_root = install_root / "var" / "logs" if install_root is not None else None

    managed_proxy: ManagedProxy | None = None
    async with _local_origins(run_root) as local_origins:
        proxy_url = options.proxy_url
        if options.binary_path is not None:
            managed_proxy = _start_managed_proxy(
                options,
                run_root,
                install_root,
                paths.repository_root,
            )
            proxy_url = managed_proxy.proxy_url
            artifacts.process_stdout_path = managed_proxy.stdout_log_path
            artifacts.process_stderr_path = managed_proxy.stderr_log_path
            log_root = managed_proxy.access_log_path.parent

        await _wait_for_proxy(proxy_url, timeout_seconds=options.request_timeout_seconds)
        scenario_results = await _run_scenarios(options, proxy_url, local_origins)
        if managed_proxy is not None:
            await _check_managed_proxy_health(managed_proxy)

    if log_root is not None:
        artifacts.access_log_tail_path = _write_log_tail(
            log_root / "access.log",
            run_root / "access.log.tail.txt",
            options.log_tail_lines,
        )
        artifacts.cache_log_tail_path = _write_log_tail(
            log_root / "cache.log",
            run_root / "cache.log.tail.txt",
            options.log_tail_lines,
        )

    if managed_proxy is not None:
        _stop_managed_proxy(managed_proxy)

    result = _write_validation_outputs(
        options=options,
        artifacts=artifacts,
        proxy_url=proxy_url,
        target_mode="managed-binary" if managed_proxy is not None else "live-proxy",
        install_root=install_root,
        scenario_results=scenario_results,
    )
    logger.info("Proxy runtime validation summary written to %s.", artifacts.summary_path)
    return result


def _resolve_run_root(paths: RepositoryPaths, artifact_root: Path | None) -> Path:
    resolved_root = resolve_path(artifact_root, base=paths.repository_root)
    if resolved_root is not None:
        return resolved_root
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return paths.artifact_root / "proxy-runtime" / timestamp


def _resolve_install_root(
    options: ProxyRuntimeValidationOptions,
    paths: RepositoryPaths,
) -> Path | None:
    resolved_install_root = resolve_path(options.install_root, base=paths.repository_root)
    if resolved_install_root is not None:
        return resolved_install_root
    if options.binary_path is None:
        return None
    resolved_binary_path = resolve_path(options.binary_path, base=paths.repository_root)
    if resolved_binary_path is None:
        return None
    return resolved_binary_path.parent.parent


@asynccontextmanager
async def _local_origins(run_root: Path) -> Any:
    cert_root = run_root / "local-origin-certs"
    cert_root.mkdir(parents=True, exist_ok=True)
    certificate_authority = trustme.CA()
    issued_cert = certificate_authority.issue_cert("localhost", "127.0.0.1")
    cert_path = cert_root / "origin.pem"
    key_path = cert_root / "origin-key.pem"
    issued_cert.cert_chain_pems[0].write_to_path(cert_path)
    issued_cert.private_key_pem.write_to_path(key_path)

    app = LocalOriginApp()
    shutdown_event = asyncio.Event()
    cleartext_port = _allocate_loopback_tcp_port()
    tls_http1_port = _allocate_loopback_tcp_port()
    tls_http2_port = _allocate_loopback_tcp_port()

    tasks = [
        asyncio.create_task(
            _serve_origin(app, f"127.0.0.1:{cleartext_port}", shutdown_event=shutdown_event)
        ),
        asyncio.create_task(
            _serve_origin(
                app,
                f"127.0.0.1:{tls_http1_port}",
                shutdown_event=shutdown_event,
                cert_path=cert_path,
                key_path=key_path,
                alpn_protocols=["http/1.1"],
            )
        ),
        asyncio.create_task(
            _serve_origin(
                app,
                f"127.0.0.1:{tls_http2_port}",
                shutdown_event=shutdown_event,
                cert_path=cert_path,
                key_path=key_path,
                alpn_protocols=["h2", "http/1.1"],
            )
        ),
    ]
    await asyncio.gather(
        _wait_for_listener("127.0.0.1", cleartext_port, 10),
        _wait_for_listener("127.0.0.1", tls_http1_port, 10),
        _wait_for_listener("127.0.0.1", tls_http2_port, 10),
    )
    try:
        yield LocalOrigins(
            cleartext_base_url=f"http://127.0.0.1:{cleartext_port}",
            tls_http1_base_url=f"https://127.0.0.1:{tls_http1_port}",
            tls_http2_base_url=f"https://127.0.0.1:{tls_http2_port}",
        )
    finally:
        shutdown_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _serve_origin(
    app: LocalOriginApp,
    bind: str,
    *,
    shutdown_event: asyncio.Event,
    cert_path: Path | None = None,
    key_path: Path | None = None,
    alpn_protocols: Sequence[str] | None = None,
) -> None:
    config = HypercornConfig()
    config.bind = [bind]
    config.accesslog = None
    config.errorlog = None
    if cert_path is not None and key_path is not None:
        config.certfile = os.fspath(cert_path)
        config.keyfile = os.fspath(key_path)
    if alpn_protocols is not None:
        config.alpn_protocols = list(alpn_protocols)
    await serve(cast(Any, app), config, shutdown_trigger=shutdown_event.wait)


async def _run_scenarios(
    options: ProxyRuntimeValidationOptions,
    proxy_url: str,
    local_origins: LocalOrigins,
) -> list[ScenarioResult]:
    limits = httpx.Limits(
        max_connections=max(32, options.burst_concurrency * 2),
        max_keepalive_connections=max(16, options.burst_concurrency),
    )
    timeout = httpx.Timeout(options.request_timeout_seconds)
    async with (
        httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout,
            trust_env=False,
            verify=False,
            http2=False,
            follow_redirects=False,
            limits=limits,
        ) as http1_client,
        httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout,
            trust_env=False,
            verify=False,
            http2=True,
            follow_redirects=False,
            limits=limits,
        ) as http2_client,
    ):
        scenarios = _scenario_definitions(options, local_origins)
        results: list[ScenarioResult] = []
        for scenario in scenarios:
            results.append(await scenario.runner(http1_client, http2_client))
        return results


def _scenario_definitions(
    options: ProxyRuntimeValidationOptions,
    origins: LocalOrigins,
) -> list[ScenarioDefinition]:
    scenarios = [
        ScenarioDefinition(
            scenario_id="local-http-bytes",
            description="HTTP/1.1 cleartext request through proxy",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-http-bytes",
                description="HTTP/1.1 cleartext request through proxy",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/bytes/16384?request_id={request_id}"
                ),
                validator=_validate_binary_body,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-gzip",
            description="Compressed gzip response through cleartext proxying",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-gzip",
                description="Compressed gzip response through cleartext proxying",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/gzip?request_id={request_id}"
                ),
                validator=_validate_encoded_json_body,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-deflate",
            description="Compressed deflate response through cleartext proxying",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-deflate",
                description="Compressed deflate response through cleartext proxying",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/deflate?request_id={request_id}"
                ),
                validator=_validate_encoded_json_body,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-brotli",
            description="Compressed brotli response through cleartext proxying",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-brotli",
                description="Compressed brotli response through cleartext proxying",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/brotli?request_id={request_id}"
                ),
                validator=_validate_encoded_json_body,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-redirect-chain",
            description="Redirect chain through proxy",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-redirect-chain",
                description="Redirect chain through proxy",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/redirect/3?request_id={request_id}"
                ),
                validator=_validate_binary_body,
                follow_redirects=True,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-drip-stream",
            description="Chunked streaming response through proxy",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-drip-stream",
                description="Chunked streaming response through proxy",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.cleartext_base_url}/drip?numbytes=32768&chunks=8&interval_ms=25&request_id={request_id}"
                ),
                validator=_validate_binary_body,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-https-http1",
            description="HTTPS tunnel with HTTP/1.1 origin response",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-https-http1",
                description="HTTPS tunnel with HTTP/1.1 origin response",
                required=True,
                client=http1,
                url_factory=lambda request_id: (
                    f"{origins.tls_http1_base_url}/bytes/8192?request_id={request_id}"
                ),
                validator=_validate_binary_body,
                expected_http_version="HTTP/1.1",
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-https-http2",
            description="HTTPS tunnel with HTTP/2 origin response",
            required=True,
            runner=lambda http1, http2: _single_request_scenario(
                scenario_id="local-https-http2",
                description="HTTPS tunnel with HTTP/2 origin response",
                required=True,
                client=http2,
                url_factory=lambda request_id: (
                    f"{origins.tls_http2_base_url}/bytes/8192?request_id={request_id}"
                ),
                validator=_validate_binary_body,
                expected_http_version="HTTP/2",
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-burst-http",
            description="Bursty concurrent HTTP/1.1 load against cleartext origin",
            required=True,
            runner=lambda http1, http2: _burst_scenario(
                scenario_id="local-burst-http",
                description="Bursty concurrent HTTP/1.1 load against cleartext origin",
                required=True,
                client=http1,
                url_factory=lambda request_id, index: (
                    f"{origins.cleartext_base_url}/bytes/4096?request_id={request_id}&sample={index}"
                ),
                validator=_validate_binary_body,
                request_count=options.burst_requests,
                concurrency=options.burst_concurrency,
            ),
        ),
        ScenarioDefinition(
            scenario_id="local-burst-http2",
            description="Bursty concurrent HTTP/2 load through HTTPS CONNECT",
            required=True,
            runner=lambda http1, http2: _burst_scenario(
                scenario_id="local-burst-http2",
                description="Bursty concurrent HTTP/2 load through HTTPS CONNECT",
                required=True,
                client=http2,
                url_factory=lambda request_id, index: (
                    f"{origins.tls_http2_base_url}/gzip?request_id={request_id}&sample={index}"
                ),
                validator=_validate_encoded_json_body,
                request_count=max(32, options.burst_requests // 2),
                concurrency=max(4, options.burst_concurrency // 2),
                expected_http_version="HTTP/2",
            ),
        ),
    ]
    if options.include_external:
        scenarios.extend(
            [
                ScenarioDefinition(
                    scenario_id="external-httpbingo",
                    description="Real-world HTTPS sanity request via httpbingo.org",
                    required=True,
                    runner=lambda http1, http2: _single_request_scenario(
                        scenario_id="external-httpbingo",
                        description="Real-world HTTPS sanity request via httpbingo.org",
                        required=True,
                        client=http1,
                        url_factory=lambda request_id: (
                            f"{_EXTERNAL_HTTP_ENDPOINT}?request_id={request_id}"
                        ),
                        validator=_validate_external_json_body,
                    ),
                ),
                ScenarioDefinition(
                    scenario_id="external-http2",
                    description="Real-world HTTP/2 sanity request via nghttp2.org",
                    required=True,
                    runner=lambda http1, http2: _single_request_scenario(
                        scenario_id="external-http2",
                        description="Real-world HTTP/2 sanity request via nghttp2.org",
                        required=True,
                        client=http2,
                        url_factory=lambda request_id: (
                            f"{_EXTERNAL_H2_ENDPOINT}?request_id={request_id}"
                        ),
                        validator=_validate_external_json_body,
                        expected_http_version="HTTP/2",
                    ),
                ),
                ScenarioDefinition(
                    scenario_id="external-tls12",
                    description="TLS 1.2-specific handshake via badssl.com",
                    required=True,
                    runner=lambda http1, http2: _single_request_scenario(
                        scenario_id="external-tls12",
                        description="TLS 1.2-specific handshake via badssl.com",
                        required=True,
                        client=http1,
                        url_factory=lambda request_id: (
                            f"{_EXTERNAL_TLS12_ENDPOINT}?request_id={request_id}"
                        ),
                        validator=_validate_badssl_response,
                    ),
                ),
                ScenarioDefinition(
                    scenario_id="external-tls13",
                    description="TLS 1.3-specific handshake via badssl.com",
                    required=True,
                    runner=lambda http1, http2: _single_request_scenario(
                        scenario_id="external-tls13",
                        description="TLS 1.3-specific handshake via badssl.com",
                        required=True,
                        client=http1,
                        url_factory=lambda request_id: (
                            f"{_EXTERNAL_TLS13_ENDPOINT}?request_id={request_id}"
                        ),
                        validator=_validate_badssl_response,
                    ),
                ),
            ]
        )
    return scenarios


async def _single_request_scenario(
    *,
    scenario_id: str,
    description: str,
    required: bool,
    client: httpx.AsyncClient,
    url_factory: Callable[[str], str],
    validator: Callable[[httpx.Response, str], ValidationOutcome],
    expected_http_version: str | None = None,
    follow_redirects: bool = False,
) -> ScenarioResult:
    request_id = uuid.uuid4().hex
    samples: list[ScenarioSample] = []
    errors: list[str] = []
    notes: list[str] = []
    start = time.perf_counter()
    try:
        response = await client.get(
            url_factory(request_id),
            headers={"X-Squid4Win-Request-ID": request_id},
            follow_redirects=follow_redirects,
        )
        if expected_http_version is not None and response.http_version != expected_http_version:
            msg = (
                f"Expected HTTP version {expected_http_version} but got "
                f"{response.http_version or '<unknown>'}."
            )
            raise RuntimeError(msg)
        validator_notes, validator_errors = validator(response, request_id)
        notes.extend(validator_notes)
        errors.extend(validator_errors)
        sample = ScenarioSample(
            request_id=request_id,
            latency_ms=(time.perf_counter() - start) * 1000,
            status_code=response.status_code,
            http_version=response.http_version,
            bytes_received=len(response.content),
            error="; ".join(validator_errors) if validator_errors else None,
        )
        samples.append(sample)
    except Exception as exc:  # noqa: BLE001
        samples.append(
            ScenarioSample(
                request_id=request_id,
                latency_ms=(time.perf_counter() - start) * 1000,
                status_code=None,
                http_version=None,
                bytes_received=0,
                error=str(exc),
            )
        )
        errors.append(str(exc))
    return _aggregate_scenario(
        scenario_id=scenario_id,
        description=description,
        required=required,
        samples=samples,
        notes=notes,
    )


async def _burst_scenario(
    *,
    scenario_id: str,
    description: str,
    required: bool,
    client: httpx.AsyncClient,
    url_factory: Callable[[str, int], str],
    validator: Callable[[httpx.Response, str], ValidationOutcome],
    request_count: int,
    concurrency: int,
    expected_http_version: str | None = None,
) -> ScenarioResult:
    semaphore = asyncio.Semaphore(concurrency)
    collected_notes: list[str] = [
        f"burst-request-count={request_count}",
        f"burst-concurrency={concurrency}",
    ]

    async def run_one(index: int) -> ScenarioSample:
        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        async with semaphore:
            try:
                response = await client.get(
                    url_factory(request_id, index),
                    headers={"X-Squid4Win-Request-ID": request_id},
                )
                if (
                    expected_http_version is not None
                    and response.http_version != expected_http_version
                ):
                    msg = (
                        f"Expected HTTP version {expected_http_version} but got "
                        f"{response.http_version or '<unknown>'}."
                    )
                    raise RuntimeError(msg)
                validator_notes, validator_errors = validator(response, request_id)
                collected_notes.extend(validator_notes)
                if validator_errors:
                    raise RuntimeError("; ".join(validator_errors))
                return ScenarioSample(
                    request_id=request_id,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    status_code=response.status_code,
                    http_version=response.http_version,
                    bytes_received=len(response.content),
                )
            except Exception as exc:  # noqa: BLE001
                return ScenarioSample(
                    request_id=request_id,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    status_code=None,
                    http_version=None,
                    bytes_received=0,
                    error=str(exc),
                )

    samples = await asyncio.gather(*(run_one(index) for index in range(request_count)))
    return _aggregate_scenario(
        scenario_id=scenario_id,
        description=description,
        required=required,
        samples=samples,
        notes=collected_notes,
    )


def _aggregate_scenario(
    *,
    scenario_id: str,
    description: str,
    required: bool,
    samples: Sequence[ScenarioSample],
    notes: Sequence[str],
) -> ScenarioResult:
    successful_samples = [sample for sample in samples if sample.error is None]
    failed_samples = [sample for sample in samples if sample.error is not None]
    latencies = sorted(sample.latency_ms for sample in successful_samples)
    http_versions = sorted(
        {sample.http_version for sample in successful_samples if sample.http_version}
    )
    errors = sorted({sample.error for sample in failed_samples if sample.error})
    return ScenarioResult(
        scenario_id=scenario_id,
        description=description,
        required=required,
        request_count=len(samples),
        success_count=len(successful_samples),
        failure_count=len(failed_samples),
        min_latency_ms=latencies[0] if latencies else None,
        mean_latency_ms=mean(latencies) if latencies else None,
        p95_latency_ms=_percentile(latencies, 95),
        http_versions=tuple(http_versions),
        request_ids=tuple(sample.request_id for sample in samples[:10]),
        errors=tuple(errors),
        notes=tuple(sorted(set(filter(None, notes)))),
    )


def _validate_binary_body(
    response: httpx.Response,
    request_id: str,
) -> ValidationOutcome:
    notes: list[str] = []
    errors: list[str] = []
    if response.status_code != 200:
        errors.append(f"Expected status 200 but got {response.status_code}.")
        return notes, errors
    expected_hash = response.headers.get("x-squid4win-content-sha256")
    body = _response_body_for_validation(response)
    if expected_hash and _sha256_hex(body) != expected_hash:
        errors.append(
            f"Expected body hash {expected_hash} but got {_sha256_hex(body)}."
        )
    echoed_request_id = response.headers.get("x-squid4win-request-id")
    if echoed_request_id != request_id:
        errors.append(
            f"Expected echoed request id {request_id} but got {echoed_request_id!r}."
        )
    return notes, errors


def _validate_encoded_json_body(
    response: httpx.Response,
    request_id: str,
) -> ValidationOutcome:
    notes, errors = _validate_binary_body(response, request_id)
    if errors:
        return notes, errors
    try:
        payload = json.loads(_response_body_for_validation(response).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"Expected JSON payload but decoding failed: {exc}")
        return notes, errors
    if payload.get("request_id") != request_id:
        errors.append(
            f"Expected JSON request id {request_id} but got {payload.get('request_id')!r}."
        )
    encoding = response.headers.get("x-squid4win-encoding")
    if encoding:
        notes.append(f"encoding={encoding}")
    return notes, errors


def _validate_external_json_body(
    response: httpx.Response,
    request_id: str,
) -> ValidationOutcome:
    notes: list[str] = []
    errors: list[str] = []
    if response.status_code != 200:
        errors.append(f"Expected status 200 but got {response.status_code}.")
        return notes, errors
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        errors.append(f"Expected JSON payload but decoding failed: {exc}")
        return notes, errors
    url = str(payload.get("url", ""))
    if request_id not in url:
        errors.append(f"Expected request id {request_id} in returned URL {url!r}.")
    return notes, errors


def _validate_badssl_response(
    response: httpx.Response,
    request_id: str,
) -> ValidationOutcome:
    del request_id
    notes: list[str] = []
    errors: list[str] = []
    if response.status_code != 200:
        errors.append(f"Expected status 200 but got {response.status_code}.")
    if b"badssl.com" not in response.content:
        notes.append("badssl-body-marker-missing")
    return notes, errors


def _start_managed_proxy(
    options: ProxyRuntimeValidationOptions,
    run_root: Path,
    install_root: Path | None,
    repository_root: Path,
) -> ManagedProxy:
    logger = get_logger("squid4win")
    resolved_binary_path = resolve_path(options.binary_path, base=repository_root)
    if resolved_binary_path is None or not resolved_binary_path.is_file():
        msg = f"Unable to find squid.exe at '{options.binary_path}'."
        raise FileNotFoundError(msg)
    effective_install_root = install_root or resolved_binary_path.parent.parent
    config_root = run_root / "managed-proxy"
    var_root = config_root / "var"
    for directory in (
        var_root / "cache",
        var_root / "logs",
        var_root / "run",
        config_root / "etc",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    proxy_port = _allocate_loopback_tcp_port()
    config_path = config_root / "etc" / "squid.conf"
    access_log_path = var_root / "logs" / "access.log"
    cache_log_path = var_root / "logs" / "cache.log"
    pid_path = var_root / "run" / "squid.pid"
    config_path.write_text(
        "\n".join(
            [
                "visible_hostname squid4win-harness",
                "eui_lookup off",
                f"http_port {proxy_port}",
                "acl localhost src 127.0.0.1/32 ::1",
                "http_access allow localhost",
                "http_access deny all",
                "dns_nameservers 1.1.1.1 1.0.0.1",
                f"cache_dir ufs {_squid_path(var_root / 'cache')} 32 16 256",
                f"coredump_dir {_squid_path(var_root / 'cache')}",
                f"access_log stdio:{_squid_path(access_log_path)}",
                f"cache_log stdio:{_squid_path(cache_log_path)}",
                "cache_store_log none",
                f"pid_filename {_squid_path(pid_path)}",
                f"mime_table {_squid_path(effective_install_root / 'etc' / 'mime.conf')}",
                f"icon_directory {_squid_path(effective_install_root / 'share' / 'icons')}",
                (
                    "error_directory "
                    f"{_squid_path(effective_install_root / 'share' / 'errors' / 'templates')}"
                ),
                (
                    "err_page_stylesheet "
                    f"{_squid_path(effective_install_root / 'etc' / 'errorpage.css')}"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    squid_environment = os.environ.copy()
    path_segments = [
        os.fspath(resolved_binary_path.parent),
        os.fspath(effective_install_root / "libexec"),
        squid_environment.get("PATH", ""),
    ]
    squid_environment["PATH"] = os.pathsep.join(segment for segment in path_segments if segment)
    _run_checked_process(
        [
            os.fspath(resolved_binary_path),
            "-k",
            "parse",
            "-f",
            os.fspath(config_path),
        ],
        environment=squid_environment,
        description="squid.exe -k parse",
        cwd=effective_install_root,
    )
    _run_checked_process(
        [
            os.fspath(resolved_binary_path),
            "-z",
            "-f",
            os.fspath(config_path),
        ],
        environment=squid_environment,
        description="squid.exe -z",
        cwd=effective_install_root,
    )
    stdout_log_path = config_root / "managed-proxy.stdout.log"
    stderr_log_path = config_root / "managed-proxy.stderr.log"
    stdout_handle = stdout_log_path.open("w", encoding="utf-8")
    stderr_handle = stderr_log_path.open("w", encoding="utf-8")
    logger.info("Starting managed Squid probe on %s using %s.", proxy_port, resolved_binary_path)
    process = subprocess.Popen(
        [
            os.fspath(resolved_binary_path),
            "-N",
            "-d",
            "1",
            "-f",
            os.fspath(config_path),
        ],
        cwd=os.fspath(effective_install_root),
        env=squid_environment,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    return ManagedProxy(
        proxy_url=f"http://127.0.0.1:{proxy_port}",
        config_path=config_path,
        stdout_log_path=stdout_log_path,
        stderr_log_path=stderr_log_path,
        access_log_path=access_log_path,
        cache_log_path=cache_log_path,
        stdout_handle=stdout_handle,
        stderr_handle=stderr_handle,
        process=process,
    )


async def _check_managed_proxy_health(managed_proxy: ManagedProxy) -> None:
    if managed_proxy.process.poll() is not None:
        stderr_text = managed_proxy.stderr_log_path.read_text(encoding="utf-8", errors="replace")
        stdout_text = managed_proxy.stdout_log_path.read_text(encoding="utf-8", errors="replace")
        msg = (
            "Managed Squid probe exited unexpectedly. "
            f"stdout tail: {stdout_text[-800:]}; stderr tail: {stderr_text[-800:]}"
        )
        raise RuntimeError(msg)


def _stop_managed_proxy(managed_proxy: ManagedProxy) -> None:
    if managed_proxy.process.poll() is None:
        managed_proxy.process.terminate()
        try:
            managed_proxy.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            managed_proxy.process.kill()
            managed_proxy.process.wait(timeout=10)
    managed_proxy.stdout_handle.close()
    managed_proxy.stderr_handle.close()


async def _wait_for_proxy(proxy_url: str, *, timeout_seconds: int) -> None:
    parsed = httpx.URL(proxy_url)
    host = parsed.host
    port = parsed.port
    if host is None or port is None:
        msg = f"Proxy URL '{proxy_url}' must include an explicit host and port."
        raise ValueError(msg)
    await _wait_for_listener(host, port, timeout_seconds)


async def _wait_for_listener(host: str, port: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except OSError:
            await asyncio.sleep(0.2)
            continue
        writer.close()
        await writer.wait_closed()
        return
    msg = f"Timed out waiting for listener on {host}:{port}."
    raise TimeoutError(msg)


def _write_validation_outputs(
    *,
    options: ProxyRuntimeValidationOptions,
    artifacts: RunArtifacts,
    proxy_url: str,
    target_mode: str,
    install_root: Path | None,
    scenario_results: Sequence[ScenarioResult],
) -> ProxyRuntimeValidationResult:
    required_failures = [
        scenario
        for scenario in scenario_results
        if scenario.required and not scenario.ok
    ]
    request_total = sum(scenario.request_count for scenario in scenario_results)
    request_failures = sum(scenario.failure_count for scenario in scenario_results)
    payload = {
        "proxy_url": proxy_url,
        "target_mode": target_mode,
        "run_root": os.fspath(artifacts.run_root),
        "install_root": None if install_root is None else os.fspath(install_root),
        "include_external": options.include_external,
        "burst_requests": options.burst_requests,
        "burst_concurrency": options.burst_concurrency,
        "scenarios": [scenario.to_json() for scenario in scenario_results],
    }
    artifacts.json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary_text = _summary_markdown(
        proxy_url=proxy_url,
        target_mode=target_mode,
        run_root=artifacts.run_root,
        install_root=install_root,
        scenario_results=scenario_results,
        request_total=request_total,
        request_failures=request_failures,
        artifacts=artifacts,
    )
    artifacts.summary_path.write_text(summary_text, encoding="utf-8")
    append_step_summary(summary_text)
    return ProxyRuntimeValidationResult(
        run_root=artifacts.run_root,
        summary_path=artifacts.summary_path,
        json_path=artifacts.json_path,
        proxy_url=proxy_url,
        target_mode=target_mode,
        scenario_count=len(scenario_results),
        failed_scenarios=len(required_failures),
        request_count=request_total,
        failed_requests=request_failures,
    )


def _summary_markdown(
    *,
    proxy_url: str,
    target_mode: str,
    run_root: Path,
    install_root: Path | None,
    scenario_results: Sequence[ScenarioResult],
    request_total: int,
    request_failures: int,
    artifacts: RunArtifacts,
) -> str:
    lines = [
        "## Proxy runtime validation",
        "",
        f"- Target mode: `{target_mode}`",
        f"- Proxy URL: `{proxy_url}`",
        f"- Run root: `{run_root}`",
        (
            f"- Install root: `{install_root}`"
            if install_root is not None
            else "- Install root: `n/a`"
        ),
        f"- Total requests: `{request_total}`",
        f"- Failed requests: `{request_failures}`",
        "",
        "| Scenario | Result | Requests | Failures | HTTP versions | p95 ms | Notes |",
        "| --- | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for scenario in scenario_results:
        notes = "; ".join(scenario.notes[:3]) if scenario.notes else ""
        versions = ", ".join(scenario.http_versions) if scenario.http_versions else "-"
        p95 = (
            f"{scenario.p95_latency_ms:.1f}"
            if scenario.p95_latency_ms is not None
            else "-"
        )
        lines.append(
            (
                "| {scenario_id} | {result} | {request_count} | {failure_count} | "
                "{versions} | {p95} | {notes} |"
            ).format(
                scenario_id=scenario.scenario_id,
                result="success" if scenario.ok else "failure",
                request_count=scenario.request_count,
                failure_count=scenario.failure_count,
                versions=versions,
                p95=p95,
                notes=notes or "-",
            )
        )
    if any(not scenario.ok for scenario in scenario_results):
        lines.extend(["", "### Failures", ""])
        for scenario in scenario_results:
            if scenario.ok:
                continue
            failure_text = "; ".join(scenario.errors) or "unknown failure"
            lines.append(f"- `{scenario.scenario_id}`: {failure_text}")
    if artifacts.access_log_tail_path is not None or artifacts.cache_log_tail_path is not None:
        lines.extend(["", "### Captured logs", ""])
        if artifacts.access_log_tail_path is not None:
            lines.append(f"- Access log tail: `{artifacts.access_log_tail_path}`")
        if artifacts.cache_log_tail_path is not None:
            lines.append(f"- Cache log tail: `{artifacts.cache_log_tail_path}`")
    if artifacts.process_stdout_path is not None or artifacts.process_stderr_path is not None:
        lines.extend(["", "### Managed proxy process logs", ""])
        if artifacts.process_stdout_path is not None:
            lines.append(f"- Managed proxy stdout: `{artifacts.process_stdout_path}`")
        if artifacts.process_stderr_path is not None:
            lines.append(f"- Managed proxy stderr: `{artifacts.process_stderr_path}`")
    lines.append("")
    return "\n".join(lines)


def _write_log_tail(source_path: Path, output_path: Path, line_count: int) -> Path | None:
    if not source_path.is_file():
        return None
    lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    output_path.write_text("\n".join(lines[-line_count:]) + "\n", encoding="utf-8")
    return output_path


def _run_checked_process(
    command: Sequence[str],
    *,
    environment: dict[str, str],
    description: str,
    cwd: Path,
) -> None:
    completed = subprocess.run(
        list(command),
        check=False,
        cwd=os.fspath(cwd),
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        msg = (
            f"{description} failed with exit code {completed.returncode}. "
            f"stdout: {completed.stdout[-800:]} stderr: {completed.stderr[-800:]}"
        )
        raise RuntimeError(msg)


def _deterministic_payload(size: int) -> bytes:
    if size <= 0:
        return b""
    digest = hashlib.sha256(_LOCAL_PAYLOAD_SEED).digest()
    repeats = (size // len(digest)) + 1
    return (digest * repeats)[:size]


def _encode_payload(payload: bytes, encoding: str) -> bytes:
    if encoding == "gzip":
        return gzip.compress(payload)
    if encoding == "deflate":
        return zlib.compress(payload)
    if encoding == "brotli":
        return brotli.compress(payload)
    msg = f"Unsupported encoding '{encoding}'."
    raise ValueError(msg)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _response_body_for_validation(response: httpx.Response) -> bytes:
    payload = response.content
    expected_hash = response.headers.get("x-squid4win-content-sha256")
    if expected_hash is None or _sha256_hex(payload) == expected_hash:
        return payload
    encoding = response.headers.get("x-squid4win-encoding") or response.headers.get(
        "content-encoding"
    )
    if encoding == "gzip":
        return gzip.decompress(payload)
    if encoding == "deflate":
        return zlib.decompress(payload)
    if encoding == "brotli":
        return brotli.decompress(payload)
    return payload


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _percentile(values: Sequence[float], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = max(0, min(len(values) - 1, round((percentile / 100) * (len(values) - 1))))
    return values[position]


def _chunk_bytes(payload: bytes, chunk_count: int) -> list[bytes]:
    chunk_size = max(1, len(payload) // chunk_count)
    return [payload[index : index + chunk_size] for index in range(0, len(payload), chunk_size)]


def _allocate_loopback_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _squid_path(path: Path) -> str:
    return os.fspath(path).replace("\\", "/")
