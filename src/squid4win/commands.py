from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from squid4win.logging_utils import get_logger
from squid4win.models import (
    AutomationPlan,
    BuildConfiguration,
    BundlePackageOptions,
    BundlePackageState,
    ConanDependencyLinkage,
    ConanLockfileUpdateOptions,
    ConanRecipeValidationOptions,
    NativeDependencySourceOptions,
    ProcessInvocation,
    RepositoryPaths,
    ServiceRunnerValidationOptions,
    ServiceRunnerValidationResult,
    SmokeTestOptions,
    SmokeTestResult,
    SquidBuildLayout,
    SquidBuildOptions,
    TrayBuildLayout,
    TrayBuildOptions,
    validate_service_name,
)
from squid4win.paths import resolve_path
from squid4win.utils.actions import append_step_summary
from squid4win.utils.actions import context as github_actions_context

if TYPE_CHECKING:
    from squid4win.runner import PlanRunner

_BUILD_MISSING_ARGUMENT = "--build=missing"
_TRAY_EXECUTABLE_NAME = "Squid4Win.Tray.exe"
_WINDOWS_MSYS2_ENV_DIRECTORY = "mingw64"
_WINDOWS_MSYS2_BASE_PACKAGES = [
    "autoconf",
    "automake",
    "libtool",
    "make",
    "mingw-w64-x86_64-make",
    "mingw-w64-x86_64-pkgconf",
    "mingw-w64-x86_64-libgnurx",
]
_WINDOWS_DEPENDENCY_SETTINGS: dict[str, dict[str, Any]] = {
    "libxml2": {
        "source_option": "libxml2_source",
        "system_package": "mingw-w64-x86_64-libxml2",
    },
    "openssl": {
        "source_option": "openssl_source",
        "feature_option": "with_openssl",
        "system_package": "mingw-w64-x86_64-openssl",
    },
    "pcre2": {
        "source_option": "pcre2_source",
        "system_package": "mingw-w64-x86_64-pcre2",
    },
    "zlib": {
        "source_option": "zlib_source",
        "system_package": "mingw-w64-x86_64-zlib",
    },
}
_WINDOWS_RUNTIME_NOTICE_ARTIFACTS: list[dict[str, Any]] = [
    {
        "id": "openssl",
        "name": "OpenSSL",
        "source_option": "openssl_source",
        "dependency_by_source": {
            "system": "msys2",
            "conan": "openssl",
        },
        "package_by_source": {
            "system": "mingw-w64-x86_64-openssl",
            "conan": "openssl",
        },
        "project_url": "https://openssl-library.org",
        "license": "spdx:Apache-2.0",
        "dlls": [
            "libcrypto-3-x64.dll",
            "libssl-3-x64.dll",
        ],
        "license_files_by_source": {
            "system": [
                "licenses\\libopenssl\\LICENSE.txt",
            ],
        },
        "license_directories_by_source": {
            "conan": [
                "licenses",
            ],
        },
    },
    {
        "id": "winpthreads",
        "name": "winpthreads",
        "dependency": "mingw-builds",
        "package": "mingw-w64-x86_64-libwinpthread",
        "project_url": "https://www.mingw-w64.org/",
        "license": "spdx:MIT AND BSD-3-Clause-Clear",
        "dlls": [
            "libwinpthread-1.dll",
        ],
        "license_files": [
            "licenses\\winpthreads\\COPYING",
            "licenses\\mingw-w64\\COPYING.MinGW-w64-runtime.txt",
        ],
    },
    {
        "id": "libgnurx",
        "name": "libgnurx",
        "dependency": "mingw-builds",
        "package": "mingw-w64-x86_64-libgnurx",
        "project_url": "https://mingw.sourceforge.io/",
        "license": "LGPL",
        "dlls": [
            "libgnurx-0.dll",
        ],
        "license_files": [
            "licenses\\mingw-libgnurx\\COPYING.LIB",
        ],
    },
]
_WINDOWS_BUILD_SETTINGS: dict[str, Any] = {
    "msys2": {
        "env": _WINDOWS_MSYS2_ENV_DIRECTORY,
        "packages": list(_WINDOWS_MSYS2_BASE_PACKAGES),
    },
    "mingw_builds": {
        "threads": "posix",
        "exception": "seh",
        "runtime": "ucrt",
    },
    "dependencies": _WINDOWS_DEPENDENCY_SETTINGS,
    "runtime_dlls": [
        "libcrypto-3-x64.dll",
        "libssl-3-x64.dll",
        "libwinpthread-1.dll",
        "libgnurx-0.dll",
    ],
    "runtime_notice_artifacts": _WINDOWS_RUNTIME_NOTICE_ARTIFACTS,
}


@dataclass(frozen=True)
class ConanContext:
    paths: RepositoryPaths
    build_root: Path
    host_profile_path: Path
    lockfile_path: Path
    layout: SquidBuildLayout


@dataclass(frozen=True)
class TrayContext:
    paths: RepositoryPaths
    build_root: Path
    project_path: Path
    publish_root: Path
    package_root: Path
    license_path: Path


@dataclass(frozen=True)
class CleanupResult:
    actions: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.issues


def _resolved_or_default(value: Path | None, default: Path, *, base: Path) -> Path:
    return resolve_path(value, base=base) or default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []

    strings: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            strings.append(text)
    return strings


def _dependency_build_settings(build_settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_dependencies = build_settings.get("dependencies") or {}
    if not isinstance(raw_dependencies, dict):
        msg = "Windows dependency metadata must be a mapping."
        raise ValueError(msg)

    dependencies: dict[str, dict[str, Any]] = {}
    for dependency_name, raw_dependency in raw_dependencies.items():
        normalized_name = str(dependency_name).strip()
        if not normalized_name:
            continue
        if not isinstance(raw_dependency, dict):
            msg = f"Windows dependency metadata for '{normalized_name}' must be a mapping."
            raise ValueError(msg)
        dependencies[normalized_name] = cast(dict[str, Any], raw_dependency)

    return dependencies


def _selected_dependency_sources(
    build_settings: dict[str, Any],
    dependency_sources: NativeDependencySourceOptions,
) -> dict[str, str]:
    option_values = dependency_sources.as_option_values()
    selected_sources: dict[str, str] = {}
    for dependency_name, dependency_settings in _dependency_build_settings(build_settings).items():
        option_name = _dependency_source_option_name(
            dependency_name,
            dependency_settings,
        )
        selected_sources[dependency_name] = _validated_dependency_source_value(
            dependency_name,
            option_name,
            option_values,
        )

    return selected_sources


def _dependency_source_option_name(
    dependency_name: str,
    dependency_settings: dict[str, Any],
) -> str:
    option_name = str(dependency_settings.get("source_option", "")).strip()
    if option_name:
        return option_name

    msg = f"Windows dependency metadata for '{dependency_name}' must declare source_option."
    raise ValueError(msg)


def _validated_dependency_source_value(
    dependency_name: str,
    option_name: str,
    option_values: dict[str, str],
) -> str:
    source_value = str(option_values.get(option_name, "")).strip().lower()
    if source_value in {"system", "conan"}:
        return source_value

    msg = (
        f"Unsupported source '{source_value}' for dependency '{dependency_name}'. "
        "Expected 'system' or 'conan'."
    )
    raise ValueError(msg)


def _recipe_host_option_arguments(
    build_settings: dict[str, Any],
    dependency_sources: NativeDependencySourceOptions,
    *,
    openssl_linkage: ConanDependencyLinkage = ConanDependencyLinkage.DEFAULT,
) -> list[str]:
    selected_dependency_sources = _selected_dependency_sources(
        build_settings,
        dependency_sources,
    )
    arguments: list[str] = []

    for dependency_name, dependency_settings in _dependency_build_settings(build_settings).items():
        option_name = str(dependency_settings.get("source_option", "")).strip()
        if not option_name:
            msg = f"Windows dependency metadata for '{dependency_name}' must declare source_option."
            raise ValueError(msg)

        arguments.extend(
            ["-o:h", f"&:{option_name}={selected_dependency_sources[dependency_name]}"]
        )

        if selected_dependency_sources[dependency_name] == "conan":
            arguments.extend(
                _conan_dependency_host_option_arguments(
                    dependency_name,
                    openssl_linkage=openssl_linkage,
                )
            )

    return arguments


def _conan_dependency_host_option_arguments(
    dependency_name: str,
    *,
    openssl_linkage: ConanDependencyLinkage,
) -> list[str]:
    if dependency_name != "openssl":
        return ["-o:h", f"{dependency_name}/*:shared=False"]

    openssl_shared = openssl_linkage.as_shared_option()
    if openssl_shared is None:
        openssl_shared = True

    return [
        "-o:h",
        f"openssl/*:shared={openssl_shared}",
    ]


def _windows_recipe_conf_arguments(
    selected_dependency_sources: dict[str, str],
) -> list[str]:
    arguments: list[str] = []

    if selected_dependency_sources.get("openssl") == "conan":
        arguments.extend(_windows_openssl_conan_conf_arguments())

    return arguments


def _windows_openssl_conan_host_option_arguments(
    selected_dependency_sources: dict[str, str],
) -> list[str]:
    if selected_dependency_sources.get("openssl") != "conan":
        return []

    return [
        "-o:h",
        "openssl/*:no_dgram=True",
        "-o:h",
        "openssl/*:no_apps=True",
    ]


def _windows_openssl_conan_conf_arguments() -> list[str]:
    # OpenSSL's MinGW build currently needs the earlier wchar/_alloca workaround
    # and explicit Windows+MinGW defines so e_os2.h/e_os.h and sha.h take
    # compatible branches before dso_win32.c reaches tlhelp32.h.
    return [
        "-c:h",
        'openssl/*:tools.build:cflags=["-include","wchar.h"]',
        "-c:h",
        (
            'openssl/*:tools.build:defines=['
            '"_WIN32",'
            '"__MINGW32__",'
            '"_alloca=__builtin_alloca"'
            "]"
        ),
    ]


def _uses_default_dependency_sources(
    dependency_sources: NativeDependencySourceOptions,
) -> bool:
    return all(source == "system" for source in dependency_sources.as_option_values().values())


def _source_specific_string(
    notice_entry: dict[str, Any],
    field_name: str,
    *,
    selected_source: str | None,
    notice_id: str,
) -> str:
    mapped_field_name = f"{field_name}_by_source"
    mapped_value = notice_entry.get(mapped_field_name)
    if mapped_value is None:
        return str(notice_entry.get(field_name, "")).strip()

    if not isinstance(mapped_value, dict):
        msg = f"Runtime notice entry '{notice_id}' field '{mapped_field_name}' must be a mapping."
        raise ValueError(msg)

    if selected_source is None:
        msg = (
            f"Runtime notice entry '{notice_id}' declared '{mapped_field_name}' without "
            "declaring source_option."
        )
        raise ValueError(msg)

    return str(mapped_value.get(selected_source, "")).strip()


def _source_specific_string_list(
    notice_entry: dict[str, Any],
    field_name: str,
    *,
    selected_source: str | None,
    notice_id: str,
) -> list[str]:
    mapped_field_name = f"{field_name}_by_source"
    mapped_value = notice_entry.get(mapped_field_name)
    if mapped_value is None:
        return _deduplicate(_string_list(notice_entry.get(field_name, [])))

    if not isinstance(mapped_value, dict):
        msg = f"Runtime notice entry '{notice_id}' field '{mapped_field_name}' must be a mapping."
        raise ValueError(msg)

    if selected_source is None:
        msg = (
            f"Runtime notice entry '{notice_id}' declared '{mapped_field_name}' without "
            "declaring source_option."
        )
        raise ValueError(msg)

    return _deduplicate(_string_list(mapped_value.get(selected_source, [])))


def _powershell_executable() -> str:
    return shutil.which("pwsh") or shutil.which("powershell") or "pwsh"


def _copy_directory_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _compress_directory_contents(source_root: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(source_root))


def _load_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"Expected a JSON object in '{path}'."
        raise ValueError(msg)
    return cast(dict[str, Any], loaded)


def _load_build_settings(_paths: RepositoryPaths) -> dict[str, Any]:
    return _WINDOWS_BUILD_SETTINGS


def _recipe_option_arguments(
    paths: RepositoryPaths,
    *,
    dependency_sources: NativeDependencySourceOptions,
    openssl_linkage: ConanDependencyLinkage = ConanDependencyLinkage.DEFAULT,
) -> list[str]:
    arguments: list[str] = []
    build_settings = _load_build_settings(paths)
    selected_dependency_sources = _selected_dependency_sources(build_settings, dependency_sources)
    msys2_settings = build_settings.get("msys2") or {}
    if isinstance(msys2_settings, dict):
        packages = _string_list(msys2_settings.get("packages", []))
        dependency_settings = _dependency_build_settings(build_settings)
        for dependency_name, dependency_setting in dependency_settings.items():
            if selected_dependency_sources.get(dependency_name) != "system":
                continue

            system_package = str(dependency_setting.get("system_package", "")).strip()
            if system_package:
                packages.append(system_package)

        if packages:
            arguments.extend(["-o:b", f"msys2/*:additional_packages={','.join(packages)}"])

    mingw_settings = build_settings.get("mingw_builds") or {}
    if isinstance(mingw_settings, dict):
        for option_name in ("threads", "exception", "runtime"):
            option_value = str(mingw_settings.get(option_name, "")).strip()
            if option_value:
                arguments.extend(["-o:b", f"mingw-builds/*:{option_name}={option_value}"])

    arguments.extend(
        _recipe_host_option_arguments(
            build_settings,
            dependency_sources,
            openssl_linkage=openssl_linkage,
        )
    )
    arguments.extend(_windows_openssl_conan_host_option_arguments(selected_dependency_sources))
    arguments.extend(_windows_recipe_conf_arguments(selected_dependency_sources))
    return arguments


def _base_conan_environment(paths: RepositoryPaths) -> dict[str, str]:
    return {"CONAN_HOME": str(paths.conan_home_path)}


def _description_suffix(options: SquidBuildOptions) -> str:
    if options.bootstrap_only:
        return "Bootstrap the repo-local Conan workspace."

    return (
        "Detect the Conan profile, refresh the lockfile when needed, source the "
        "CCI-style Squid recipe, and build the staged native Squid bundle."
    )


def _resolve_conan_context(
    repository_root: Path | None,
    build_root: Path | None,
    configuration: BuildConfiguration,
    host_profile_path: Path | None,
    lockfile_path: Path | None,
    dependency_sources: NativeDependencySourceOptions,
) -> ConanContext:
    paths = RepositoryPaths.discover(repository_root)
    resolved_build_root = _resolved_or_default(
        build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    resolved_host_profile_path = _resolved_or_default(
        host_profile_path,
        paths.conan_root / "profiles" / "msys2-mingw-x64",
        base=paths.repository_root,
    )
    layout = SquidBuildLayout.create(
        paths.repository_root,
        resolved_build_root,
        configuration,
        host_profile_path=resolved_host_profile_path,
    )
    resolved_lockfile_path = resolve_path(lockfile_path, base=paths.repository_root)
    if resolved_lockfile_path is None:
        resolved_lockfile_path = (
            layout.repo_lockfile_path
            if _uses_default_dependency_sources(dependency_sources)
            else layout.build_lock_path
        )

    return ConanContext(
        paths=paths,
        build_root=resolved_build_root,
        host_profile_path=resolved_host_profile_path,
        lockfile_path=resolved_lockfile_path,
        layout=layout,
    )


def _resolve_tray_context(options: TrayBuildOptions) -> TrayContext:
    paths = RepositoryPaths.discover(options.repository_root)
    build_root = _resolved_or_default(
        options.build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    layout = TrayBuildLayout.create(paths.repository_root, build_root, options.configuration)
    project_path = _resolved_or_default(
        options.project_path,
        paths.tray_project_path,
        base=paths.repository_root,
    )
    publish_root = _resolved_or_default(
        options.publish_root,
        layout.publish_root,
        base=paths.repository_root,
    )
    package_root = _resolved_or_default(
        options.package_root,
        layout.package_root,
        base=paths.repository_root,
    )

    return TrayContext(
        paths=paths,
        build_root=build_root,
        project_path=project_path,
        publish_root=publish_root,
        package_root=package_root,
        license_path=paths.repository_root / "LICENSE",
    )


def _load_conan_graph_info(
    context: ConanContext,
    *,
    build_profile: str,
    configuration: BuildConfiguration,
    dependency_sources: NativeDependencySourceOptions,
) -> dict[str, Any]:
    completed = subprocess.run(
        (
            "conan",
            "graph",
            "info",
            str(context.paths.conan_recipe_root),
            "--profile:host",
            str(context.host_profile_path),
            "--profile:build",
            build_profile,
            "--lockfile",
            str(context.lockfile_path),
            "-s:h",
            f"build_type={configuration.value}",
            "-s:b",
            f"build_type={configuration.value}",
            _BUILD_MISSING_ARGUMENT,
            *_recipe_option_arguments(
                context.paths,
                dependency_sources=dependency_sources,
            ),
            "--format=json",
        ),
        cwd=context.paths.repository_root,
        env={**os.environ, **_base_conan_environment(context.paths)},
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        output = "\n".join(
            part.strip()
            for part in (completed.stdout, completed.stderr)
            if part is not None and part.strip()
        )
        msg = output or "conan graph info failed."
        raise RuntimeError(msg)

    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, dict):
        msg = "Expected 'conan graph info --format=json' to return a JSON object."
        raise ValueError(msg)

    return cast(dict[str, Any], loaded)


def _conan_graph_nodes(graph_info: dict[str, Any]) -> list[dict[str, Any]]:
    graph = graph_info.get("graph")
    if not isinstance(graph, dict):
        msg = "Expected the Conan graph info payload to contain a 'graph' object."
        raise ValueError(msg)

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, dict):
        msg = "Expected the Conan graph info payload to contain graph.nodes."
        raise ValueError(msg)

    return [cast(dict[str, Any], node) for node in raw_nodes.values() if isinstance(node, dict)]


def _graph_dependency_node(
    graph_info: dict[str, Any],
    dependency_name: str,
) -> dict[str, Any]:
    for node in _conan_graph_nodes(graph_info):
        node_name = str(node.get("name", "")).strip()
        node_ref = str(node.get("ref", "")).strip()
        if node_name == dependency_name or node_ref.startswith(f"{dependency_name}/"):
            return node

    msg = f"Unable to locate the '{dependency_name}' dependency in the Conan graph."
    raise FileNotFoundError(msg)


def _package_reference_from_graph_node(graph_node: dict[str, Any]) -> str:
    ref = str(graph_node.get("ref", "")).strip()
    package_id = str(graph_node.get("package_id", "")).strip()
    prev = str(graph_node.get("prev", "")).strip()
    if not ref or not package_id or not prev:
        msg = f"Unable to derive a Conan package reference from graph node {graph_node!r}."
        raise ValueError(msg)

    return f"{ref}:{package_id}#{prev}"


def _resolve_dependency_package_root(
    paths: RepositoryPaths,
    graph_node: dict[str, Any],
) -> Path:
    completed = subprocess.run(
        ("conan", "cache", "path", _package_reference_from_graph_node(graph_node)),
        cwd=paths.repository_root,
        env={**os.environ, **_base_conan_environment(paths)},
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        output = "\n".join(
            part.strip()
            for part in (completed.stdout, completed.stderr)
            if part is not None and part.strip()
        )
        msg = output or "conan cache path failed."
        raise RuntimeError(msg)

    package_root = Path(completed.stdout.strip())
    if not package_root.is_dir():
        msg = f"Resolved Conan package root '{package_root}' does not exist."
        raise FileNotFoundError(msg)

    return package_root


def _runtime_dependency_names(
    build_settings: dict[str, Any],
    *,
    dependency_sources: NativeDependencySourceOptions,
) -> list[str]:
    dependency_names = ["mingw-builds", "msys2"]
    for dependency_name, selected_source in _selected_dependency_sources(
        build_settings,
        dependency_sources,
    ).items():
        if selected_source == "conan":
            dependency_names.append(dependency_name)

    return _deduplicate(dependency_names)


def _resolve_dependency_metadata(
    context: ConanContext,
    *,
    build_profile: str,
    configuration: BuildConfiguration,
    dependency_names: list[str],
    dependency_sources: NativeDependencySourceOptions,
) -> tuple[dict[str, str], dict[str, Path]]:
    graph_info = _load_conan_graph_info(
        context,
        build_profile=build_profile,
        configuration=configuration,
        dependency_sources=dependency_sources,
    )
    dependency_refs: dict[str, str] = {}
    dependency_roots: dict[str, Path] = {}
    for dependency_name in dependency_names:
        graph_node = _graph_dependency_node(graph_info, dependency_name)
        dependency_ref = str(graph_node.get("ref", "")).strip()
        if not dependency_ref:
            msg = f"Unable to resolve a Conan reference for '{dependency_name}'."
            raise ValueError(msg)

        dependency_refs[dependency_name] = dependency_ref
        dependency_roots[dependency_name] = _resolve_dependency_package_root(
            context.paths,
            graph_node,
        )

    return dependency_refs, dependency_roots


def _append_existing_directory(
    directories: list[Path],
    seen_directories: set[str],
    candidate: Path,
) -> None:
    if not candidate.is_dir():
        return

    candidate_key = os.path.normcase(os.fspath(candidate.resolve(strict=False)))
    if candidate_key in seen_directories:
        return

    seen_directories.add(candidate_key)
    directories.append(candidate)


def _runtime_dll_source_directories(
    dependency_roots: dict[str, Path],
    *,
    msys2_env_directory: str,
) -> list[Path]:
    source_directories: list[Path] = []
    seen_directories: set[str] = set()

    _append_windows_runtime_tool_directories(
        source_directories,
        seen_directories,
        dependency_roots,
        msys2_env_directory=msys2_env_directory,
    )
    _append_dependency_runtime_bin_directories(
        source_directories,
        seen_directories,
        dependency_roots,
    )

    if not source_directories:
        msg = "Unable to locate runtime DLL source directories from the Conan dependency graph."
        raise FileNotFoundError(msg)

    return source_directories


def _append_windows_runtime_tool_directories(
    source_directories: list[Path],
    seen_directories: set[str],
    dependency_roots: dict[str, Path],
    *,
    msys2_env_directory: str,
) -> None:
    mingw_root = dependency_roots.get("mingw-builds")
    if mingw_root is not None:
        _append_existing_directory(source_directories, seen_directories, mingw_root / "bin")

    _append_msys2_runtime_directories(
        source_directories,
        seen_directories,
        dependency_roots.get("msys2"),
        msys2_env_directory=msys2_env_directory,
    )


def _append_msys2_runtime_directories(
    source_directories: list[Path],
    seen_directories: set[str],
    msys2_root: Path | None,
    *,
    msys2_env_directory: str,
) -> None:
    if msys2_root is None:
        return

    _append_existing_directory(
        source_directories,
        seen_directories,
        msys2_root / "bin" / "msys64" / msys2_env_directory / "bin",
    )
    _append_existing_directory(
        source_directories,
        seen_directories,
        msys2_root / "bin" / "msys64" / "usr" / "bin",
    )


def _append_dependency_runtime_bin_directories(
    source_directories: list[Path],
    seen_directories: set[str],
    dependency_roots: dict[str, Path],
) -> None:
    for dependency_name, dependency_root in dependency_roots.items():
        if dependency_name not in {"mingw-builds", "msys2"}:
            _append_existing_directory(
                source_directories,
                seen_directories,
                dependency_root / "bin",
            )


def _native_executable_directories(bundle_root: Path) -> list[Path]:
    executable_directories = sorted(
        {executable_path.parent for executable_path in bundle_root.rglob("*.exe")},
        key=lambda path: os.fspath(path).lower(),
    )
    if not executable_directories:
        msg = f"Expected at least one executable under '{bundle_root}'."
        raise FileNotFoundError(msg)

    return executable_directories


def _require_squid_executable(bundle_root: Path) -> Path:
    squid_candidates = (
        bundle_root / "sbin" / "squid.exe",
        bundle_root / "bin" / "squid.exe",
    )
    squid_executable = next(
        (candidate for candidate in squid_candidates if candidate.is_file()),
        None,
    )
    if squid_executable is None:
        msg = f"Expected squid.exe under '{bundle_root}'."
        raise FileNotFoundError(msg)

    return squid_executable


def _bundle_native_runtime_dlls(
    bundle_root: Path,
    build_settings: dict[str, Any],
    dependency_roots: dict[str, Path],
    *,
    msys2_env_directory: str,
) -> list[str]:
    runtime_dlls = _string_list(build_settings.get("runtime_dlls", []))
    if not runtime_dlls:
        msg = "Windows build metadata must declare runtime_dlls for the staged bundle."
        raise ValueError(msg)

    runtime_dll_sources = _runtime_dll_source_directories(
        dependency_roots,
        msys2_env_directory=msys2_env_directory,
    )
    executable_directories = _native_executable_directories(bundle_root)
    copied_runtime_dlls: list[str] = []
    missing_runtime_dlls: list[str] = []
    for runtime_dll in runtime_dlls:
        runtime_dll_source_path = _runtime_dll_source_path(
            runtime_dll,
            runtime_dll_sources,
        )
        if runtime_dll_source_path is None:
            missing_runtime_dlls.append(runtime_dll)
            continue

        _copy_runtime_dll_to_executables(
            runtime_dll_source_path,
            runtime_dll,
            executable_directories,
        )
        copied_runtime_dlls.append(runtime_dll)

    if missing_runtime_dlls:
        msg = (
            "Unable to locate the required Windows runtime DLLs in the Conan dependency graph: "
            + ", ".join(missing_runtime_dlls)
            + "."
        )
        raise FileNotFoundError(msg)

    return copied_runtime_dlls


def _runtime_dll_source_path(runtime_dll: str, runtime_dll_sources: list[Path]) -> Path | None:
    return next(
        (
            source_directory / runtime_dll
            for source_directory in runtime_dll_sources
            if (source_directory / runtime_dll).is_file()
        ),
        None,
    )


def _copy_runtime_dll_to_executables(
    runtime_dll_source_path: Path,
    runtime_dll: str,
    executable_directories: list[Path],
) -> None:
    for executable_directory in executable_directories:
        shutil.copy2(runtime_dll_source_path, executable_directory / runtime_dll)


def _copy_runtime_notice_files(
    bundle_root: Path,
    destination_root: Path,
    dependency_root: Path,
    *,
    notice_id: str,
    notice_entry: dict[str, Any],
) -> list[str]:
    destination_root.mkdir(parents=True, exist_ok=True)
    copied_notice_files: list[str] = []
    for relative_path in _deduplicate(_string_list(notice_entry.get("license_files", []))):
        source_path = dependency_root / Path(relative_path)
        if not source_path.is_file():
            msg = (
                f"Unable to locate the runtime notice file '{relative_path}' for entry "
                f"'{notice_id}' under '{dependency_root}'."
            )
            raise FileNotFoundError(msg)

        destination_path = destination_root / source_path.name
        shutil.copy2(source_path, destination_path)
        copied_notice_files.append(_relative_package_path(destination_path, bundle_root))

    for relative_directory in _deduplicate(
        _string_list(notice_entry.get("license_directories", []))
    ):
        source_directory = dependency_root / Path(relative_directory)
        if not source_directory.is_dir():
            msg = (
                f"Unable to locate the runtime notice directory '{relative_directory}' for "
                f"entry '{notice_id}' under '{dependency_root}'."
            )
            raise FileNotFoundError(msg)

        copied_directory_files = False
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file():
                continue
            relative_source_path = source_path.relative_to(dependency_root)
            destination_path = destination_root / relative_source_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
            copied_notice_files.append(_relative_package_path(destination_path, bundle_root))
            copied_directory_files = True

        if not copied_directory_files:
            msg = (
                f"Runtime notice directory '{relative_directory}' for entry '{notice_id}' "
                "did not contain any files."
            )
            raise RuntimeError(msg)

    if not copied_notice_files:
        msg = f"Runtime notice entry '{notice_id}' did not resolve any notice files."
        raise RuntimeError(msg)

    return copied_notice_files


def _validate_runtime_notice_coverage(
    bundled_runtime_dlls: list[str],
    declared_runtime_dlls: set[str],
) -> None:
    bundled_runtime_dll_set = set(bundled_runtime_dlls)
    missing_notice_entries = sorted(bundled_runtime_dll_set - declared_runtime_dlls)
    if missing_notice_entries:
        msg = (
            "The bundled Windows runtime DLLs are missing notice mappings in the Python metadata: "
            + ", ".join(missing_notice_entries)
            + "."
        )
        raise ValueError(msg)

    unused_notice_entries = sorted(declared_runtime_dlls - bundled_runtime_dll_set)
    if unused_notice_entries:
        msg = (
            "Windows runtime notice metadata declares DLLs that were not bundled into the "
            "staged payload: " + ", ".join(unused_notice_entries) + "."
        )
        raise ValueError(msg)


def _harvest_runtime_notice_bundle(
    bundle_root: Path,
    build_settings: dict[str, Any],
    bundled_runtime_dlls: list[str],
    dependency_roots: dict[str, Path],
    dependency_refs: dict[str, str],
    *,
    dependency_sources: NativeDependencySourceOptions,
) -> list[dict[str, Any]]:
    raw_notice_entries = cast(list[Any], build_settings.get("runtime_notice_artifacts", []))
    if not raw_notice_entries:
        msg = "Windows build metadata must declare runtime_notice_artifacts."
        raise ValueError(msg)

    notice_root = bundle_root / "licenses" / "third-party" / "windows-runtime"
    declared_runtime_dlls: set[str] = set()
    harvested_notice_entries: list[dict[str, Any]] = []
    selected_dependency_options = dependency_sources.as_option_values()
    for raw_notice_entry in raw_notice_entries:
        if not isinstance(raw_notice_entry, dict):
            msg = "Runtime notice entries in the Windows build metadata must be mappings."
            raise ValueError(msg)

        notice_entry = cast(dict[str, Any], raw_notice_entry)
        notice_id = str(notice_entry.get("id", "")).strip()
        if not notice_id:
            msg = "Each Windows runtime notice entry must declare a non-empty id."
            raise ValueError(msg)

        runtime_dlls = _deduplicate(_string_list(notice_entry.get("dlls", [])))
        if not runtime_dlls:
            msg = f"Runtime notice entry '{notice_id}' must declare at least one bundled DLL."
            raise ValueError(msg)

        source_option = str(notice_entry.get("source_option", "")).strip()
        selected_source = None
        if source_option:
            selected_source = str(selected_dependency_options.get(source_option, "")).strip()
            if selected_source not in {"system", "conan"}:
                msg = (
                    f"Runtime notice entry '{notice_id}' declared source_option="
                    f"'{source_option}', but no supported dependency source was selected."
                )
                raise ValueError(msg)

        dependency_name = _source_specific_string(
            notice_entry,
            "dependency",
            selected_source=selected_source,
            notice_id=notice_id,
        )
        if not dependency_name:
            msg = f"Runtime notice entry '{notice_id}' must declare a dependency."
            raise ValueError(msg)

        dependency_root = dependency_roots.get(dependency_name)
        if dependency_root is None:
            msg = f"Unable to locate dependency '{dependency_name}' for '{notice_id}'."
            raise FileNotFoundError(msg)

        copied_notice_files = _copy_runtime_notice_files(
            bundle_root,
            notice_root / notice_id,
            dependency_root,
            notice_id=notice_id,
            notice_entry={
                **notice_entry,
                "license_files": _source_specific_string_list(
                    notice_entry,
                    "license_files",
                    selected_source=selected_source,
                    notice_id=notice_id,
                ),
                "license_directories": _source_specific_string_list(
                    notice_entry,
                    "license_directories",
                    selected_source=selected_source,
                    notice_id=notice_id,
                ),
            },
        )
        harvested_notice_entries.append(
            {
                "id": notice_id,
                "name": str(notice_entry.get("name", notice_id)).strip(),
                "package": (
                    _source_specific_string(
                        notice_entry,
                        "package",
                        selected_source=selected_source,
                        notice_id=notice_id,
                    )
                    or notice_id
                ),
                "source_dependency": dependency_refs.get(dependency_name, dependency_name),
                "license": str(notice_entry.get("license", "")).strip(),
                "project_url": str(notice_entry.get("project_url", "")).strip(),
                "dlls": runtime_dlls,
                "notice_files": copied_notice_files,
            }
        )
        declared_runtime_dlls.update(runtime_dlls)

    _validate_runtime_notice_coverage(bundled_runtime_dlls, declared_runtime_dlls)
    return harvested_notice_entries


def _collect_tray_notice_bundle(
    bundle_root: Path,
    tray_package_root: Path,
) -> list[dict[str, Any]]:
    manifest_path = tray_package_root / "licenses" / "third-party-package-manifest.json"
    if not manifest_path.is_file():
        msg = f"Expected the tray third-party notice manifest at '{manifest_path}'."
        raise FileNotFoundError(msg)

    manifest = _load_json_object(manifest_path)
    tray_notice_packages: list[dict[str, Any]] = []
    for raw_package in cast(list[Any], manifest.get("packages", [])):
        if not isinstance(raw_package, dict):
            msg = f"Unexpected tray notice entry in '{manifest_path}'."
            raise ValueError(msg)

        package_entry = cast(dict[str, Any], dict(raw_package))
        copied_notice_files: list[str] = []
        for notice_file in _deduplicate(_string_list(package_entry.get("notice_files", []))):
            source_path = tray_package_root / Path(notice_file)
            if not source_path.is_file():
                msg = (
                    f"Unable to locate the tray third-party notice file '{notice_file}' "
                    f"under '{tray_package_root}'."
                )
                raise FileNotFoundError(msg)

            destination_path = bundle_root / Path(notice_file)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
            copied_notice_files.append(_relative_package_path(destination_path, bundle_root))

        package_entry["notice_files"] = copied_notice_files
        package_entry["shipped_assets"] = _deduplicate(
            _string_list(package_entry.get("shipped_assets", []))
        )
        tray_notice_packages.append(package_entry)

    return tray_notice_packages


def _tray_source_manifest(
    repository_root: Path,
    tray_package_root: Path,
    tray_notice_packages: list[dict[str, Any]],
) -> dict[str, Any]:
    tray_manifest: dict[str, Any] = {
        "project": "src/tray/Squid4Win.Tray",
        "third_party_packages": tray_notice_packages,
    }
    try:
        relative_package_root = tray_package_root.resolve(strict=False).relative_to(
            repository_root.resolve(strict=False)
        )
    except ValueError:
        return tray_manifest

    tray_manifest["package_root"] = relative_package_root.as_posix()
    return tray_manifest


def _runtime_notice_lines(runtime_notice_packages: list[dict[str, Any]]) -> list[str]:
    notice_lines: list[str] = []
    for notice_entry in runtime_notice_packages:
        asset_list = ", ".join(
            [
                str(asset).strip()
                for asset in cast(list[Any], notice_entry.get("dlls", []))
                if str(asset).strip()
            ]
        )
        entry_line = f"- {notice_entry.get('name', notice_entry.get('id', 'runtime'))}"
        if asset_list:
            entry_line += f" [{asset_list}]"
        if notice_entry.get("license"):
            entry_line += f" - license: {notice_entry['license']}"
        if notice_entry.get("source_dependency"):
            entry_line += f"; source: {notice_entry['source_dependency']}"
        notice_lines.append(entry_line)
        for notice_file in cast(list[Any], notice_entry.get("notice_files", [])):
            notice_lines.append(f"  - {notice_file}")

    return notice_lines


def _tray_notice_lines(tray_notice_packages: list[dict[str, Any]]) -> list[str]:
    notice_lines: list[str] = []
    for package_entry in tray_notice_packages:
        asset_list = ", ".join(
            [
                str(asset).strip()
                for asset in cast(list[Any], package_entry.get("shipped_assets", []))
                if str(asset).strip()
            ]
        )
        entry_line = f"- {package_entry.get('id', 'tray-package')}"
        if asset_list:
            entry_line += f" [{asset_list}]"
        if package_entry.get("license"):
            entry_line += f" - license: {package_entry['license']}"
        if package_entry.get("project_url"):
            entry_line += f"; project: {package_entry['project_url']}"
        notice_lines.append(entry_line)
        for notice_file in cast(list[Any], package_entry.get("notice_files", [])):
            notice_lines.append(f"  - {notice_file}")

    return notice_lines


def _third_party_notice_lines(
    metadata: dict[str, Any],
    runtime_notice_packages: list[dict[str, Any]],
    tray_notice_packages: list[dict[str, Any]],
) -> list[str]:
    notice_lines = [
        "Squid4Win third-party notice bundle",
        "",
        (
            f"This payload stages Squid {metadata['version']} from the upstream source archive "
            "listed in licenses/source-manifest.json."
        ),
        (
            "Repository-local automation and packaging code in this project are licensed "
            "under GPL-2.0-or-later; see licenses/Repository-LICENSE.txt."
        ),
        "",
        "Bundled notice files:",
        "- licenses/source-manifest.json",
        "- licenses/Repository-LICENSE.txt",
        "- licenses/Squid-COPYING.txt (when the upstream source tree is available locally)",
    ]

    component_lines = [
        *_runtime_notice_lines(runtime_notice_packages),
        *_tray_notice_lines(tray_notice_packages),
    ]
    if component_lines:
        notice_lines.extend(
            (
                "",
                "Bundled third-party components:",
                "- Squid upstream sources and license text: licenses/Squid-COPYING.txt",
            )
        )
        notice_lines.extend(component_lines)

    notice_lines.extend(
        (
            "",
            "Machine-readable provenance for the staged payload lives in "
            "licenses/source-manifest.json.",
        )
    )
    return notice_lines


def _write_source_manifest(
    paths: RepositoryPaths,
    licenses_root: Path,
    metadata: dict[str, Any],
    *,
    configuration_label: str,
    msys2_env_directory: str,
    bundled_runtime_dlls: list[str],
    runtime_notice_packages: list[dict[str, Any]],
    tray_notice_packages: list[dict[str, Any]],
    tray_package_root: Path | None,
) -> None:
    source_manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "configuration": configuration_label,
        "squid": {
            "version": str(metadata["version"]),
            "tag": str(metadata["tag"]),
            "source_archive": str(cast(dict[str, Any], metadata["assets"])["source_archive"]),
            "source_signature": str(
                cast(dict[str, Any], metadata["assets"]).get("source_signature", "")
            ),
            "source_archive_sha256": str(
                cast(dict[str, Any], metadata["assets"])["source_archive_sha256"]
            ),
        },
        "repository": {"name": "squid4win", "license": "GPL-2.0-or-later"},
        "windows_runtime": {
            "msys2_env": msys2_env_directory,
            "dlls": bundled_runtime_dlls,
            "packages": runtime_notice_packages,
        },
    }
    if tray_package_root is not None:
        source_manifest["tray"] = _tray_source_manifest(
            paths.repository_root,
            tray_package_root,
            tray_notice_packages,
        )

    (licenses_root / "source-manifest.json").write_text(
        json.dumps(source_manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_third_party_notices(
    bundle_root: Path,
    metadata: dict[str, Any],
    runtime_notice_packages: list[dict[str, Any]],
    tray_notice_packages: list[dict[str, Any]],
) -> None:
    notices_content = "\n".join(
        _third_party_notice_lines(metadata, runtime_notice_packages, tray_notice_packages)
    )
    (bundle_root / "THIRD-PARTY-NOTICES.txt").write_text(
        notices_content + "\n",
        encoding="utf-8",
    )


def _ensure_mime_configuration(
    bundle_root: Path,
    source_root: Path,
    config_directory: Path,
) -> None:
    mime_destination_path = config_directory / "mime.conf"
    if mime_destination_path.is_file():
        return

    mime_candidates = (
        config_directory / "mime.conf.default",
        source_root / "src" / "mime.conf.default",
    )
    mime_source_path = next(
        (candidate for candidate in mime_candidates if candidate.is_file()),
        None,
    )
    if mime_source_path is None:
        msg = f"Unable to locate mime.conf for the assembled bundle under '{bundle_root}'."
        raise FileNotFoundError(msg)

    shutil.copy2(mime_source_path, mime_destination_path)


def _copy_packaging_support_files(
    paths: RepositoryPaths,
    bundle_root: Path,
    source_root: Path,
) -> tuple[Path, Path, Path]:
    licenses_root = bundle_root / "licenses"
    installer_support_root = bundle_root / "installer"
    config_directory = bundle_root / "etc"
    for directory_path in (licenses_root, installer_support_root, config_directory):
        directory_path.mkdir(parents=True, exist_ok=True)

    shutil.copy2(
        paths.scripts_root / "installer" / "Manage-SquidService.ps1",
        installer_support_root / "svc.ps1",
    )
    shutil.copy2(
        paths.scripts_root / "Assert-SquidServiceName.ps1",
        installer_support_root / "Assert-SquidServiceName.ps1",
    )
    shutil.copy2(
        paths.repository_root / "packaging" / "defaults" / "squid.conf.template",
        config_directory / "squid.conf.template",
    )
    (config_directory / "squid.conf").unlink(missing_ok=True)
    shutil.copy2(paths.repository_root / "LICENSE", licenses_root / "Repository-LICENSE.txt")
    _ensure_mime_configuration(bundle_root, source_root, config_directory)

    squid_copying_path = source_root / "COPYING"
    if squid_copying_path.is_file():
        shutil.copy2(squid_copying_path, licenses_root / "Squid-COPYING.txt")

    return licenses_root, installer_support_root, config_directory


def _materialize_staged_squid_bundle(
    context: ConanContext,
    options: SquidBuildOptions,
    release_metadata: dict[str, Any],
) -> None:
    if not context.layout.conan_install_root.is_dir():
        msg = f"Expected the pure Conan install root at '{context.layout.conan_install_root}'."
        raise FileNotFoundError(msg)

    build_settings = _load_build_settings(context.paths)
    msys2_settings = cast(dict[str, Any], build_settings.get("msys2") or {})
    msys2_env_directory = str(msys2_settings.get("env", "mingw64")).lower()
    stage_root = context.layout.stage_root
    _remove_tree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    _copy_directory_contents(context.layout.conan_install_root, stage_root)

    tray_context: TrayContext | None = None
    if options.with_tray:
        tray_context = _resolve_tray_context(
            TrayBuildOptions(
                repository_root=context.paths.repository_root,
                configuration=options.configuration,
                build_root=context.build_root,
            )
        )
        tray_bin_root = tray_context.package_root / "bin"
        if not tray_bin_root.is_dir():
            msg = f"Expected the tray package binaries at '{tray_bin_root}'."
            raise FileNotFoundError(msg)

        _copy_directory_contents(tray_bin_root, stage_root)

    bundled_runtime_dlls: list[str] = []
    runtime_notice_packages: list[dict[str, Any]] = []
    dependency_refs: dict[str, str] = {}
    dependency_roots: dict[str, Path] = {}
    if options.with_runtime_dlls:
        dependency_refs, dependency_roots = _resolve_dependency_metadata(
            context,
            build_profile=options.build_profile,
            configuration=options.configuration,
            dependency_names=_runtime_dependency_names(
                build_settings,
                dependency_sources=options.dependency_sources,
            ),
            dependency_sources=options.dependency_sources,
        )
        bundled_runtime_dlls = _bundle_native_runtime_dlls(
            stage_root,
            build_settings,
            dependency_roots,
            msys2_env_directory=msys2_env_directory,
        )
        runtime_notice_packages = _harvest_runtime_notice_bundle(
            stage_root,
            build_settings,
            bundled_runtime_dlls,
            dependency_roots,
            dependency_refs,
            dependency_sources=options.dependency_sources,
        )

    if options.with_packaging_support:
        source_root = (
            context.paths.conan_recipe_root / "sources" / f"squid-{release_metadata['version']}"
        )
        licenses_root, _, _ = _copy_packaging_support_files(
            context.paths,
            stage_root,
            source_root,
        )
        tray_notice_packages: list[dict[str, Any]] = []
        if tray_context is not None:
            tray_notice_packages = _collect_tray_notice_bundle(
                stage_root,
                tray_context.package_root,
            )
        _write_source_manifest(
            context.paths,
            licenses_root,
            release_metadata,
            configuration_label=context.layout.configuration_label,
            msys2_env_directory=msys2_env_directory,
            bundled_runtime_dlls=bundled_runtime_dlls,
            runtime_notice_packages=runtime_notice_packages,
            tray_notice_packages=tray_notice_packages,
            tray_package_root=None if tray_context is None else tray_context.package_root,
        )
        _write_third_party_notices(
            stage_root,
            release_metadata,
            runtime_notice_packages,
            tray_notice_packages,
        )

    _require_squid_executable(stage_root)


def _infer_build_root_from_stage_root(
    squid_stage_root: Path, configuration: BuildConfiguration
) -> Path | None:
    configuration_label = configuration.value.lower()
    if squid_stage_root.name.lower() != configuration_label:
        return None

    install_root = squid_stage_root.parent
    if install_root.name.lower() != "install":
        return None

    return install_root.parent


def _join_phrases(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"

    leading = ", ".join(values[:-1])
    return f"{leading}, and {values[-1]}"


def _bundle_requires_tray(options: BundlePackageOptions) -> bool:
    return options.require_tray or options.create_portable_zip or options.build_installer


def _bundle_requires_notices(options: BundlePackageOptions) -> bool:
    return options.require_notices or options.create_portable_zip or options.build_installer


def _bundle_prerequisite_reasons(
    options: BundlePackageOptions,
    *,
    bundle_state: BundlePackageState,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not bundle_state.stage_root_exists:
        reasons.append("missing staged bundle root")
    if bundle_state.staged_squid_executable_path is None:
        reasons.append("staged bundle missing squid.exe")
    if not bundle_state.packaging_support_available:
        reasons.append("staged bundle missing packaging support files")
    if _bundle_requires_tray(options) and not bundle_state.staged_tray_available:
        reasons.append("staged bundle missing Squid4Win.Tray.exe")
    if _bundle_requires_notices(options) and not bundle_state.staged_notices_available:
        reasons.append("staged bundle missing THIRD-PARTY-NOTICES.txt")

    return tuple(reasons)


def _bundle_summary(
    options: BundlePackageOptions,
    *,
    prerequisite_reasons: tuple[str, ...],
) -> str:
    actions = ["stage the release payload"]
    if options.create_portable_zip:
        actions.append("create the portable zip")
    if options.build_installer:
        actions.append("build the MSI")

    action_summary = _join_phrases(actions)
    if not prerequisite_reasons:
        return f"{action_summary.capitalize()}."

    reason_summary = "; ".join(prerequisite_reasons)
    return f"Materialize missing bundle prerequisites ({reason_summary}), then {action_summary}."


def _single_step_plan(
    repository_root: Path,
    *,
    name: str,
    invocation: ProcessInvocation,
) -> AutomationPlan:
    return AutomationPlan(
        name=name,
        summary=invocation.description,
        repository_root=repository_root,
        commands=(invocation,),
    )


def _signing_invocation(
    paths: RepositoryPaths,
    *,
    target_path: Path,
    recurse: bool,
    description: str,
) -> ProcessInvocation:
    command = [
        _powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-File",
        str(paths.scripts_root / "Invoke-AuthenticodeSigning.ps1"),
        "-Path",
        str(target_path),
        "-RepositoryRoot",
        str(paths.repository_root),
        "-RequireMatches",
    ]
    if recurse:
        command.append("-Recurse")

    return ProcessInvocation(
        description=description,
        command=tuple(command),
        cwd=paths.repository_root,
    )


def _log_dry_run_footer(message: str) -> int:
    logger = get_logger("squid4win")
    logger.info(message)
    return 0


def _run_invocation(
    runner: PlanRunner,
    repository_root: Path,
    *,
    name: str,
    invocation: ProcessInvocation,
) -> None:
    runner.run(_single_step_plan(repository_root, name=name, invocation=invocation))


def _derive_installer_version(metadata_path: Path) -> str:
    metadata = _load_json_object(metadata_path)
    raw_version = str(metadata.get("version", "")).strip()
    numeric_parts = [int(part) for part in re.split(r"\D+", raw_version) if part]
    if not numeric_parts:
        msg = f"Unable to derive an installer version from '{raw_version}'."
        raise ValueError(msg)

    normalized_parts = numeric_parts[:3]
    while len(normalized_parts) < 3:
        normalized_parts.append(0)

    revision = 0
    github_context = github_actions_context()
    if github_context.run_number is not None:
        revision = min(github_context.run_number, 65535)

    normalized_parts.append(revision)
    return ".".join(str(part) for part in normalized_parts)


@contextmanager
def _build_lock(lock_path: Path, work_root: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        msg = (
            f"Another squid-build invocation is already using '{work_root}'. Wait for it "
            f"to finish or remove the stale lock at '{lock_path}' after verifying that "
            "no build is running."
        )
        raise OSError(msg) from exc

    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(f"pid={os.getpid()}\n")
            handle.write(f"started_at={datetime.now(UTC).isoformat(timespec='seconds')}\n")
            handle.write(f"work_root={work_root}\n")
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _relative_package_path(path: Path, package_root: Path) -> str:
    return path.relative_to(package_root).as_posix()


def _deduplicate(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


def _nuget_global_packages_root() -> Path:
    configured_packages_root = os.getenv("NUGET_PACKAGES", "").strip()
    if configured_packages_root:
        packages_root = Path(configured_packages_root)
        if packages_root.is_dir():
            return packages_root

    result = subprocess.run(
        ["dotnet", "nuget", "locals", "global-packages", "--list"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        msg = (
            "dotnet nuget locals failed with exit code "
            f"{result.returncode}: {result.stderr.strip()}"
        )
        raise RuntimeError(msg)

    for line in result.stdout.splitlines():
        label, separator, value = line.partition(":")
        if separator and label.strip().lower() == "global-packages":
            packages_root = Path(value.strip())
            if packages_root.is_dir():
                return packages_root

    msg = "Unable to resolve the NuGet global-packages cache location."
    raise RuntimeError(msg)


def _read_nuget_package_metadata(package_path: Path) -> dict[str, str]:
    nuspec_path = next(package_path.glob("*.nuspec"), None)
    if nuspec_path is None or not nuspec_path.is_file():
        return {}

    nuspec_text = nuspec_path.read_text(encoding="utf-8")

    def _metadata_text(name: str) -> str:
        match = re.search(
            rf"<{name}\b[^>]*>(.*?)</{name}>",
            nuspec_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return match.group(1).strip() if match is not None else ""

    return {
        "license": _metadata_text("license") or _metadata_text("licenseUrl"),
        "project_url": _metadata_text("projectUrl"),
    }


def _copy_nuget_notice_files(package_path: Path, package_root: Path, package_id: str) -> list[str]:
    notice_candidates: list[Path] = []
    seen_paths: set[str] = set()
    for pattern in ("LICENSE*", "NOTICE*", "THIRD-PARTY-NOTICES*"):
        for candidate in sorted(package_path.glob(pattern)):
            if not candidate.is_file():
                continue

            candidate_key = os.path.normcase(os.fspath(candidate))
            if candidate_key in seen_paths:
                continue

            seen_paths.add(candidate_key)
            notice_candidates.append(candidate)

    if not notice_candidates:
        msg = (
            "Unable to locate license or notice files in the NuGet package cache "
            f"for '{package_id}' at {package_path}."
        )
        raise RuntimeError(msg)

    destination_root = package_root / "licenses" / "third-party" / "nuget" / package_id
    destination_root.mkdir(parents=True, exist_ok=True)

    copied_notice_files: list[str] = []
    for source_path in notice_candidates:
        destination_path = destination_root / source_path.name
        shutil.copy2(source_path, destination_path)
        copied_notice_files.append(_relative_package_path(destination_path, package_root))

    return copied_notice_files


def _harvest_tray_notice_manifest(publish_root: Path, package_root: Path) -> Path:
    deps_path = publish_root / "Squid4Win.Tray.deps.json"
    if not deps_path.is_file():
        msg = f"Expected the published deps manifest at '{deps_path}'."
        raise FileNotFoundError(msg)

    deps_data = _load_json_object(deps_path)
    runtime_target_name = str(
        cast(dict[str, Any], deps_data.get("runtimeTarget", {})).get("name", "")
    ).strip()
    runtime_target = cast(
        dict[str, Any],
        cast(dict[str, Any], deps_data.get("targets", {})).get(runtime_target_name, {}),
    )
    libraries = cast(dict[str, Any], deps_data.get("libraries", {}))
    global_packages_root = _nuget_global_packages_root()
    third_party_packages: list[dict[str, Any]] = []

    for library_name, library_data in sorted(libraries.items()):
        library_mapping = cast(dict[str, Any], library_data)
        if str(library_mapping.get("type", "")).strip().lower() != "package":
            continue

        target_entry = cast(dict[str, Any], runtime_target.get(library_name, {}))
        runtime_assets = cast(dict[str, Any], target_entry.get("runtime", {}))
        runtime_target_assets = cast(dict[str, Any], target_entry.get("runtimeTargets", {}))
        shipped_assets = _deduplicate(
            [
                str(asset_path).replace("\\", "/")
                for asset_path in [*runtime_assets.keys(), *runtime_target_assets.keys()]
                if str(asset_path).strip()
            ]
        )
        if not shipped_assets:
            continue

        package_id, _, package_version = library_name.partition("/")
        if not package_id or not package_version:
            msg = f"Unexpected NuGet library key '{library_name}' in '{deps_path}'."
            raise RuntimeError(msg)

        package_path_value = str(library_mapping.get("path", "")).strip()
        if not package_path_value:
            msg = f"The deps manifest did not declare a package path for '{library_name}'."
            raise RuntimeError(msg)

        package_path = global_packages_root / Path(package_path_value.replace("/", os.sep))
        if not package_path.is_dir():
            msg = (
                "Expected the NuGet package cache directory for "
                f"'{library_name}' at '{package_path}'."
            )
            raise RuntimeError(msg)

        package_metadata = _read_nuget_package_metadata(package_path)
        notice_files = _copy_nuget_notice_files(package_path, package_root, package_id)
        third_party_packages.append(
            {
                "id": package_id,
                "version": package_version,
                "license": package_metadata.get("license", ""),
                "project_url": package_metadata.get("project_url", ""),
                "shipped_assets": shipped_assets,
                "notice_files": notice_files,
            }
        )

    manifest_path = package_root / "licenses" / "third-party-package-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "packages": third_party_packages,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def build_squid_plan(options: SquidBuildOptions) -> AutomationPlan:
    context = _resolve_conan_context(
        options.repository_root,
        options.build_root,
        options.configuration,
        options.host_profile_path,
        options.lockfile_path,
        options.dependency_sources,
    )
    if options.additional_configure_args:
        msg = (
            "The standalone Conan recipe no longer accepts ad hoc configure arguments from "
            "the Python CLI. Express Squid feature changes through recipe options or "
                        "recipe defaults instead."
        )
        raise ValueError(msg)

    recipe_option_arguments = _recipe_option_arguments(
        context.paths,
        dependency_sources=options.dependency_sources,
    )
    base_environment = _base_conan_environment(context.paths)

    commands = [
        ProcessInvocation(
            description="Detect the Conan default profile for the repo-local CONAN_HOME.",
            command=("conan", "profile", "detect", "--force"),
            environment=base_environment,
        )
    ]
    if not options.bootstrap_only:
        if options.refresh_lockfile or not context.lockfile_path.is_file():
            commands.append(
                ProcessInvocation(
                    description="Refresh the Conan lockfile for the Squid recipe.",
                    command=(
                        "conan",
                        "lock",
                        "create",
                        str(context.paths.conan_recipe_root),
                        "--profile:host",
                        str(context.host_profile_path),
                        "--profile:build",
                        options.build_profile,
                        "--lockfile-out",
                        str(context.lockfile_path),
                        "-s:h",
                        f"build_type={options.configuration.value}",
                        "-s:b",
                        f"build_type={options.configuration.value}",
                        _BUILD_MISSING_ARGUMENT,
                        *recipe_option_arguments,
                    ),
                    environment=base_environment,
                )
            )

        commands.append(
            ProcessInvocation(
                description="Resolve the Squid recipe source tree.",
                command=("conan", "source", str(context.paths.conan_recipe_root)),
                environment=base_environment,
            )
        )

        commands.append(
            ProcessInvocation(
                description="Build the pure native Squid package with the Squid recipe.",
                command=(
                    "conan",
                    "build",
                    str(context.paths.conan_recipe_root),
                    "-of",
                    str(context.layout.conan_output_root),
                    "-pr:h",
                    str(context.host_profile_path),
                    "-pr:b",
                    options.build_profile,
                    "--lockfile",
                    str(context.lockfile_path),
                    "-s:h",
                    f"build_type={options.configuration.value}",
                    "-s:b",
                    f"build_type={options.configuration.value}",
                    "-c:h",
                    f"tools.build:jobs={options.make_jobs}",
                    "-c:b",
                    f"tools.build:jobs={options.make_jobs}",
                    _BUILD_MISSING_ARGUMENT,
                    *recipe_option_arguments,
                ),
                environment=base_environment,
            )
        )

    return AutomationPlan(
        name="squid-build",
        summary=_description_suffix(options),
        repository_root=context.paths.repository_root,
        commands=tuple(commands),
    )


def build_tray_plan(options: TrayBuildOptions) -> AutomationPlan:
    context = _resolve_tray_context(options)
    return AutomationPlan(
        name="tray-build",
        summary="Publish the .NET tray app and materialize the reusable tray package root.",
        repository_root=context.paths.repository_root,
        commands=(
            ProcessInvocation(
                description="Publish the tray app with dotnet publish.",
                command=(
                    "dotnet",
                    "publish",
                    str(context.project_path),
                    "-c",
                    options.configuration.value,
                    "-o",
                    str(context.publish_root),
                    "--nologo",
                    "-p:SelfContained=false",
                    "-p:PublishSingleFile=false",
                ),
            ),
        ),
    )


def _default_recipe_validation_profile_path(paths: RepositoryPaths) -> Path:
    profile_name = "msys2-mingw-x64" if os.name == "nt" else "linux-gcc-x64"
    return paths.conan_root / "profiles" / profile_name


def _resolved_recipe_validation_profile_path(
    paths: RepositoryPaths,
    host_profile_path: Path | None,
) -> Path:
    return _resolved_or_default(
        host_profile_path,
        _default_recipe_validation_profile_path(paths),
        base=paths.repository_root,
    )


def build_conan_recipe_validation_plan(
    options: ConanRecipeValidationOptions,
) -> AutomationPlan:
    paths = RepositoryPaths.discover(options.repository_root)
    resolved_host_profile_path = _resolved_recipe_validation_profile_path(
        paths,
        options.host_profile_path,
    )
    build_settings = _load_build_settings(paths)
    host_option_arguments = _recipe_host_option_arguments(
        build_settings,
        options.dependency_sources,
        openssl_linkage=options.openssl_linkage,
    )
    recipe_option_arguments = (
        _recipe_option_arguments(
            paths,
            dependency_sources=options.dependency_sources,
            openssl_linkage=options.openssl_linkage,
        )
        if os.name == "nt"
        else host_option_arguments
    )
    base_environment = _base_conan_environment(paths)

    return AutomationPlan(
        name="conan-recipe-validate",
        summary=(
            "Detect the Conan profile and validate the standalone Squid recipe "
            "with conan create."
        ),
        repository_root=paths.repository_root,
        commands=(
            ProcessInvocation(
                description="Detect the Conan default profile for the repo-local CONAN_HOME.",
                command=("conan", "profile", "detect", "--force"),
                environment=base_environment,
            ),
            ProcessInvocation(
                description="Validate the Squid recipe with conan create.",
                command=(
                    "conan",
                    "create",
                    str(paths.conan_recipe_root),
                    "--profile:host",
                    str(resolved_host_profile_path),
                    "--profile:build",
                    options.build_profile,
                    "-s:h",
                    f"build_type={options.configuration.value}",
                    "-s:b",
                    f"build_type={options.configuration.value}",
                    _BUILD_MISSING_ARGUMENT,
                    *recipe_option_arguments,
                ),
                environment=base_environment,
            ),
        ),
    )


def build_conan_lockfile_update_plan(options: ConanLockfileUpdateOptions) -> AutomationPlan:
    context = _resolve_conan_context(
        options.repository_root,
        options.build_root,
        options.configuration,
        options.host_profile_path,
        options.lockfile_path,
        options.dependency_sources,
    )
    recipe_option_arguments = _recipe_option_arguments(
        context.paths,
        dependency_sources=options.dependency_sources,
    )
    base_environment = _base_conan_environment(context.paths)

    return AutomationPlan(
        name="conan-lockfile-update",
        summary="Detect the Conan profile and refresh the selected lockfile.",
        repository_root=context.paths.repository_root,
        commands=(
            ProcessInvocation(
                description="Detect the Conan default profile for the repo-local CONAN_HOME.",
                command=("conan", "profile", "detect", "--force"),
                environment=base_environment,
            ),
            ProcessInvocation(
                description="Refresh the Conan lockfile for the Squid recipe.",
                command=(
                    "conan",
                    "lock",
                    "create",
                    str(context.paths.conan_recipe_root),
                    "--profile:host",
                    str(context.host_profile_path),
                    "--profile:build",
                    options.build_profile,
                    "--lockfile-out",
                    str(context.lockfile_path),
                    "-s:h",
                    f"build_type={options.configuration.value}",
                    "-s:b",
                    f"build_type={options.configuration.value}",
                    _BUILD_MISSING_ARGUMENT,
                    *recipe_option_arguments,
                ),
                environment=base_environment,
            ),
        ),
    )


def build_bundle_plan(options: BundlePackageOptions) -> AutomationPlan:
    paths = RepositoryPaths.discover(options.repository_root)
    build_root = _resolved_or_default(
        options.build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    if options.squid_stage_root is not None and options.build_root is None:
        explicit_stage_root = resolve_path(options.squid_stage_root, base=paths.repository_root)
        if explicit_stage_root is not None:
            inferred_build_root = _infer_build_root_from_stage_root(
                explicit_stage_root,
                options.configuration,
            )
            if inferred_build_root is not None:
                build_root = inferred_build_root

    artifact_root = _resolved_or_default(
        options.artifact_root,
        paths.artifact_root,
        base=paths.repository_root,
    )
    squid_stage_root = _resolved_or_default(
        options.squid_stage_root,
        build_root / "install" / options.configuration.value.lower(),
        base=paths.repository_root,
    )
    installer_project_path = _resolved_or_default(
        options.installer_project_path,
        paths.installer_project_path,
        base=paths.repository_root,
    )
    bundle_state = BundlePackageState.inspect(
        paths.repository_root,
        build_root,
        options.configuration,
        squid_stage_root=squid_stage_root,
        artifact_root=artifact_root,
        installer_project_path=installer_project_path,
    )
    prerequisite_reasons = _bundle_prerequisite_reasons(options, bundle_state=bundle_state)
    buildable_stage_root = build_root / "install" / options.configuration.value.lower()
    if prerequisite_reasons and squid_stage_root != buildable_stage_root:
        msg = (
            "bundle-package can only materialize missing prerequisites when "
            "--squid-stage-root matches '<build-root>\\install\\<configuration>'. "
            f"Expected '{buildable_stage_root}', but received '{squid_stage_root}'."
        )
        raise ValueError(msg)

    if options.build_installer and not installer_project_path.is_file():
        msg = f"Installer project '{installer_project_path}' does not exist."
        raise FileNotFoundError(msg)

    require_tray = _bundle_requires_tray(options)
    commands: list[ProcessInvocation] = []
    if prerequisite_reasons:
        squid_build_plan = build_squid_plan(
            SquidBuildOptions(
                repository_root=paths.repository_root,
                configuration=options.configuration,
                build_root=build_root,
                with_tray=require_tray,
                with_runtime_dlls=True,
                with_packaging_support=True,
                dependency_sources=options.dependency_sources,
            )
        )
        commands.extend(squid_build_plan.commands)

    install_payload_root = artifact_root / "install-root"
    if options.sign_payload_files:
        commands.append(
            _signing_invocation(
                paths,
                target_path=install_payload_root,
                recurse=True,
                description="Sign the staged payload files in the install root.",
            )
        )

    if options.build_installer:
        product_version = options.product_version or _derive_installer_version(
            paths.squid_release_metadata_path
        )
        commands.append(
            ProcessInvocation(
                description="Build the WiX installer project from the staged payload.",
                command=(
                    "dotnet",
                    "build",
                    str(installer_project_path),
                    "-c",
                    options.configuration.value,
                    "-t:Rebuild",
                    "--nologo",
                    f"-p:InstallerPayloadRoot={install_payload_root}",
                    f"-p:ProductVersion={product_version}",
                    f"-p:SquidServiceName={options.service_name}",
                ),
            )
        )
        if options.sign_msi:
            commands.append(
                _signing_invocation(
                    paths,
                    target_path=artifact_root / "squid4win.msi",
                    recurse=False,
                    description="Sign the built MSI artifact.",
                )
            )

    return AutomationPlan(
        name="bundle-package",
        summary=_bundle_summary(options, prerequisite_reasons=prerequisite_reasons),
        repository_root=paths.repository_root,
        commands=tuple(commands),
    )


def run_tray_build(options: TrayBuildOptions, runner: PlanRunner, *, execute: bool) -> int:
    logger = get_logger("squid4win")
    context = _resolve_tray_context(options)
    plan = build_tray_plan(options)

    if not execute:
        logger.info(
            "The Python automation will publish the tray app into '%s' and materialize "
            "the reusable package root at '%s'.",
            context.publish_root,
            context.package_root,
        )
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to publish the tray app and harvest notices."
        )

    if shutil.which("dotnet") is None:
        msg = "The dotnet CLI is required to materialize the tray package root."
        raise FileNotFoundError(msg)
    if not context.project_path.is_file():
        msg = f"The tray app project '{context.project_path}' was not found."
        raise FileNotFoundError(msg)
    if not context.license_path.is_file():
        msg = f"The repository license '{context.license_path}' was not found."
        raise FileNotFoundError(msg)

    _remove_tree(context.publish_root)
    _remove_tree(context.package_root)
    (context.package_root / "bin").mkdir(parents=True, exist_ok=True)
    (context.package_root / "licenses").mkdir(parents=True, exist_ok=True)
    context.publish_root.mkdir(parents=True, exist_ok=True)

    runner.run(plan)

    published_tray_executable_path = context.publish_root / _TRAY_EXECUTABLE_NAME
    if not published_tray_executable_path.is_file():
        msg = f"Expected the published tray executable at '{published_tray_executable_path}'."
        raise FileNotFoundError(msg)

    _copy_directory_contents(context.publish_root, context.package_root / "bin")
    shutil.copy2(context.license_path, context.package_root / "licenses" / "LICENSE")
    manifest_path = _harvest_tray_notice_manifest(context.publish_root, context.package_root)

    packaged_tray_executable_path = context.package_root / "bin" / _TRAY_EXECUTABLE_NAME
    if not packaged_tray_executable_path.is_file():
        msg = f"Expected the packaged tray executable at '{packaged_tray_executable_path}'."
        raise FileNotFoundError(msg)
    if not manifest_path.is_file():
        msg = f"Expected the tray third-party manifest at '{manifest_path}'."
        raise FileNotFoundError(msg)

    logger.info("Tray package root ready at %s.", context.package_root)
    return 0


def run_squid_build(options: SquidBuildOptions, runner: PlanRunner, *, execute: bool) -> int:
    logger = get_logger("squid4win")
    context = _resolve_conan_context(
        options.repository_root,
        options.build_root,
        options.configuration,
        options.host_profile_path,
        options.lockfile_path,
        options.dependency_sources,
    )
    metadata_path = _resolved_or_default(
        options.metadata_path,
        context.paths.squid_release_metadata_path,
        base=context.paths.repository_root,
    )
    plan = build_squid_plan(options)

    if not execute:
        if options.with_tray and not options.bootstrap_only:
            tray_plan = build_tray_plan(
                TrayBuildOptions(
                    repository_root=context.paths.repository_root,
                    configuration=options.configuration,
                    build_root=context.build_root,
                )
            )
            runner.describe(tray_plan)
        if options.clean and not options.bootstrap_only:
            logger.info(
                "The existing build outputs under '%s' will be removed first.",
                context.build_root,
            )
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to run Conan and the Python-owned staging steps."
        )

    if shutil.which("conan") is None:
        msg = "The conan CLI is not available on PATH. Run uv sync first."
        raise FileNotFoundError(msg)

    context.paths.conan_home_path.mkdir(parents=True, exist_ok=True)
    context.layout.conan_output_root.mkdir(parents=True, exist_ok=True)
    context.lockfile_path.parent.mkdir(parents=True, exist_ok=True)

    if options.with_tray and not options.bootstrap_only:
        run_tray_build(
            TrayBuildOptions(
                repository_root=context.paths.repository_root,
                configuration=options.configuration,
                build_root=context.build_root,
            ),
            runner,
            execute=True,
        )

    release_metadata = _load_json_object(metadata_path)
    with _build_lock(context.layout.build_lock_path, context.layout.conan_output_root):
        if options.clean and not options.bootstrap_only:
            source_root = (
                context.paths.conan_recipe_root
                / "sources"
                / (f"squid-{release_metadata['version']}")
            )
            tray_layout = TrayBuildLayout.create(
                context.paths.repository_root,
                context.build_root,
                options.configuration,
            )
            for path_to_remove in (
                context.layout.conan_output_root,
                context.layout.stage_root,
                context.layout.work_root,
                source_root,
                tray_layout.publish_root.parent,
            ):
                _remove_tree(path_to_remove)
            context.layout.conan_output_root.mkdir(parents=True, exist_ok=True)

        runner.run(plan)
        if not options.bootstrap_only:
            _materialize_staged_squid_bundle(context, options, release_metadata)

    if not options.bootstrap_only and not context.layout.stage_root.is_dir():
        msg = (
            "The Python staging pass finished without materializing the staged bundle at "
            f"'{context.layout.stage_root}'."
        )
        raise FileNotFoundError(msg)

    if not options.bootstrap_only:
        logger.info("Staged native bundle ready at %s.", context.layout.stage_root)
    return 0


def _install_root_from_binary_path(binary_path: Path) -> Path:
    binary_directory = binary_path.parent
    if binary_directory.name.lower() not in {"bin", "sbin"}:
        msg = (
            f"Unable to infer the staged install root from binary path '{binary_path}'. "
            "Expected squid.exe under a bin\\ or sbin\\ directory."
        )
        raise ValueError(msg)

    return binary_directory.parent


def _discover_squid_binary(install_root: Path) -> Path:
    squid_candidates = (
        install_root / "sbin" / "squid.exe",
        install_root / "bin" / "squid.exe",
    )
    squid_executable = next(
        (candidate for candidate in squid_candidates if candidate.is_file()),
        None,
    )
    if squid_executable is not None:
        return squid_executable

    discovered_binary = next(
        (candidate for candidate in sorted(install_root.rglob("squid.exe")) if candidate.is_file()),
        None,
    )
    if discovered_binary is None:
        msg = f"Unable to find squid.exe under '{install_root}'."
        raise FileNotFoundError(msg)

    return discovered_binary


def _smoke_test_manifest_sections(
    install_root: Path,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], Path | None]:
    source_manifest_path = install_root / "licenses" / "source-manifest.json"
    if not source_manifest_path.is_file():
        return [], [], [], None

    source_manifest = _load_json_object(source_manifest_path)
    runtime_dlls: list[str] = []
    runtime_notice_packages: list[dict[str, Any]] = []
    tray_notice_packages: list[dict[str, Any]] = []

    windows_runtime = source_manifest.get("windows_runtime")
    if isinstance(windows_runtime, dict):
        runtime_dlls = _string_list(windows_runtime.get("dlls", []))
        runtime_notice_packages = [
            cast(dict[str, Any], package)
            for package in cast(list[Any], windows_runtime.get("packages", []))
            if isinstance(package, dict)
        ]

    tray_section = source_manifest.get("tray")
    if isinstance(tray_section, dict):
        tray_notice_packages = [
            cast(dict[str, Any], package)
            for package in cast(list[Any], tray_section.get("third_party_packages", []))
            if isinstance(package, dict)
        ]

    return runtime_dlls, runtime_notice_packages, tray_notice_packages, source_manifest_path


def _notice_package_label(package: dict[str, Any], default_label: str) -> str:
    for key in ("id", "name"):
        value = str(package.get(key, "")).strip()
        if value:
            return value
    return default_label


def _assert_notice_files_present(
    packages: list[dict[str, Any]],
    *,
    install_root: Path,
    label: str,
) -> None:
    missing_notice_files: list[str] = []
    for package in packages:
        package_name = _notice_package_label(package, label)
        for notice_file in _string_list(package.get("notice_files", [])):
            notice_path = install_root / Path(notice_file.replace("/", os.sep))
            if not notice_path.is_file():
                missing_notice_files.append(f"{package_name}: {notice_file}")

    if missing_notice_files:
        msg = f"Missing {label} notice files: {'; '.join(missing_notice_files)}"
        raise FileNotFoundError(msg)


def _run_checked_capture(
    command: tuple[str, ...],
    *,
    description: str,
) -> str:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    combined_output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part is not None and part.strip()
    )
    if completed.returncode != 0:
        msg = f"{description} failed with exit code {completed.returncode}."
        if combined_output:
            msg = f"{msg} Output: {combined_output}"
        raise RuntimeError(msg)

    return combined_output


def _tail_text_file(path: Path, *, max_lines: int = 40) -> str | None:
    if not path.is_file():
        return None

    lines = deque[str](maxlen=max_lines)
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines.append(line.rstrip("\r\n"))

    if not lines:
        return ""

    return "\n".join(lines)


def _relative_summary_path(path: Path, root: Path) -> str:
    try:
        relative_path = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return os.fspath(path)

    relative_text = relative_path.as_posix()
    return relative_text or "."


def _write_smoke_test_summary(
    result: SmokeTestResult,
    *,
    require_notices: bool,
) -> None:
    runtime_dll_summary = (
        ", ".join(result.runtime_dlls)
        if result.runtime_dlls
        else "skipped (no source-manifest runtime DLL contract present)"
    )
    runtime_notice_summary = (
        ", ".join(
            sorted(
                _notice_package_label(package, "runtime-package")
                for package in result.runtime_notice_packages
            )
        )
        if result.runtime_notice_packages
        else ("required" if require_notices else "not required")
    )
    tray_notice_summary = (
        ", ".join(
            sorted(
                _notice_package_label(package, "tray-package")
                for package in result.tray_notice_packages
            )
        )
        if result.tray_notice_packages
        else ("required" if require_notices else "not required")
    )
    executable_directory_summary = ", ".join(
        _relative_summary_path(path, result.install_root) for path in result.executable_directories
    )

    summary_lines = [
        "## Smoke test",
        "",
        f"- Binary: `{result.binary_path}`",
        f"- Install root: `{result.install_root}`",
        f"- Version: `{result.version}`",
        f"- Runtime DLLs: `{runtime_dll_summary}`",
        f"- Runtime notice packages: `{runtime_notice_summary}`",
        f"- Tray notice packages: `{tray_notice_summary}`",
        f"- Executable directories: `{executable_directory_summary}`",
    ]
    if result.notices_path is not None:
        summary_lines.append(f"- Notices bundle: `{result.notices_path}`")
    if result.security_file_certgen_path is not None:
        summary_lines.append(f"- security_file_certgen: `{result.security_file_certgen_path}`")

    append_step_summary("\n".join(summary_lines) + "\n")


def run_smoke_test(options: SmokeTestOptions, runner: PlanRunner, *, execute: bool) -> int:
    del runner
    logger = get_logger("squid4win")
    paths = RepositoryPaths.discover(options.repository_root)
    build_root = _resolved_or_default(
        options.build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    squid_stage_root = _resolved_or_default(
        options.squid_stage_root,
        build_root / "install" / options.configuration.value.lower(),
        base=paths.repository_root,
    )
    metadata_path = _resolved_or_default(
        options.metadata_path,
        paths.squid_release_metadata_path,
        base=paths.repository_root,
    )
    resolved_binary_path = resolve_path(options.binary_path, base=paths.repository_root)

    if not execute:
        logger.info(
            "The Python automation will validate the staged Squid bundle under '%s'.",
            squid_stage_root if resolved_binary_path is None else resolved_binary_path,
        )
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to validate the staged Squid bundle."
        )

    release_metadata = _load_json_object(metadata_path)
    expected_version = str(release_metadata.get("version", "")).strip()
    if not expected_version:
        msg = f"Expected a non-empty Squid version in '{metadata_path}'."
        raise ValueError(msg)

    install_root = (
        _install_root_from_binary_path(resolved_binary_path)
        if resolved_binary_path is not None
        else squid_stage_root
    )
    binary_path = resolved_binary_path or _discover_squid_binary(install_root)
    if not binary_path.is_file():
        msg = f"Unable to find squid.exe under '{install_root}'."
        raise FileNotFoundError(msg)

    runtime_dlls, runtime_notice_packages, tray_notice_packages, source_manifest_path = (
        _smoke_test_manifest_sections(install_root)
    )
    notices_path = install_root / "THIRD-PARTY-NOTICES.txt"
    if options.require_notices and source_manifest_path is not None and not notices_path.is_file():
        msg = (
            f"Expected THIRD-PARTY-NOTICES.txt under '{install_root}' whenever "
            "source-manifest.json is present."
        )
        raise FileNotFoundError(msg)

    executable_directories = tuple(_native_executable_directories(install_root))
    if runtime_dlls:
        missing_runtime_dll_entries: list[str] = []
        for executable_directory in executable_directories:
            missing_runtime_dlls = [
                runtime_dll
                for runtime_dll in runtime_dlls
                if not (executable_directory / runtime_dll).is_file()
            ]
            if not missing_runtime_dlls:
                continue

            relative_directory = _relative_summary_path(executable_directory, install_root)
            missing_runtime_dll_entries.append(
                f"{relative_directory}: {', '.join(missing_runtime_dlls)}"
            )

        if missing_runtime_dll_entries:
            msg = f"Missing staged runtime DLLs: {'; '.join(missing_runtime_dll_entries)}"
            raise FileNotFoundError(msg)

        if options.require_notices and not runtime_notice_packages:
            msg = (
                "Expected source-manifest.json to declare packaged notice files for the "
                "bundled runtime DLLs."
            )
            raise ValueError(msg)

        if options.require_notices:
            runtime_notice_dlls = sorted(
                {
                    runtime_dll
                    for package in runtime_notice_packages
                    for runtime_dll in _string_list(package.get("dlls", []))
                }
            )
            missing_runtime_notice_dlls = [
                runtime_dll
                for runtime_dll in runtime_dlls
                if runtime_dll not in runtime_notice_dlls
            ]
            extra_runtime_notice_dlls = [
                runtime_dll
                for runtime_dll in runtime_notice_dlls
                if runtime_dll not in runtime_dlls
            ]
            if missing_runtime_notice_dlls or extra_runtime_notice_dlls:
                msg = (
                    "Runtime notice metadata does not match the bundled runtime DLL "
                    "contract. Missing: "
                    + ", ".join(missing_runtime_notice_dlls)
                    + "; Extra: "
                    + ", ".join(extra_runtime_notice_dlls)
                )
                raise ValueError(msg)

    if options.require_notices and runtime_notice_packages:
        _assert_notice_files_present(
            runtime_notice_packages,
            install_root=install_root,
            label="runtime",
        )
    if (
        options.require_notices
        and (install_root / "System.ServiceProcess.ServiceController.dll").is_file()
        and not tray_notice_packages
    ):
        msg = (
            "Expected source-manifest.json to declare tray-package notice metadata for "
            "the shipped System.ServiceProcess.ServiceController.dll."
        )
        raise ValueError(msg)
    if options.require_notices and tray_notice_packages:
        _assert_notice_files_present(
            tray_notice_packages,
            install_root=install_root,
            label="tray-package",
        )

    version_output = _run_checked_capture(
        (os.fspath(binary_path), "-v"),
        description="squid.exe -v",
    )
    if expected_version not in version_output:
        msg = f"Expected squid version {expected_version} but version output was: {version_output}"
        raise RuntimeError(msg)

    security_file_certgen_path = install_root / "libexec" / "security_file_certgen.exe"
    if security_file_certgen_path.is_file():
        security_file_certgen_output = _run_checked_capture(
            (os.fspath(security_file_certgen_path), "-h"),
            description="security_file_certgen.exe -h",
        )
        if re.search(r"usage:\s+security_file_certgen", security_file_certgen_output) is None:
            msg = (
                "security_file_certgen.exe -h returned unexpected output: "
                f"{security_file_certgen_output}"
            )
            raise RuntimeError(msg)

    result = SmokeTestResult(
        binary_path=binary_path,
        install_root=install_root,
        version=expected_version,
        executable_directories=executable_directories,
        runtime_dlls=tuple(runtime_dlls),
        runtime_notice_packages=tuple(runtime_notice_packages),
        tray_notice_packages=tuple(tray_notice_packages),
        notices_path=notices_path if notices_path.is_file() else None,
        security_file_certgen_path=(
            security_file_certgen_path if security_file_certgen_path.is_file() else None
        ),
    )
    _write_smoke_test_summary(result, require_notices=options.require_notices)
    logger.info("Smoke tests passed for %s.", binary_path)
    return 0


def _is_windows_administrator() -> bool:
    if os.name != "nt":
        return False

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError, OSError:
        return False


def _assert_runner_validation_prerequisites(
    *,
    allow_non_runner_execution: bool,
) -> None:
    if os.name != "nt":
        msg = "Service runner validation is only supported on Windows."
        raise RuntimeError(msg)

    if not allow_non_runner_execution and github_actions_context().enabled is not True:
        msg = (
            "Service runner validation performs MSI install and Windows service control. "
            "Run it on an isolated GitHub Actions runner or pass "
            "--allow-non-runner-execution only when the environment is explicitly "
            "dedicated to this validation."
        )
        raise RuntimeError(msg)

    if not _is_windows_administrator():
        msg = (
            "Service runner validation requires administrator privileges because it "
            "installs an MSI and controls a Windows service."
        )
        raise RuntimeError(msg)


def _validation_token() -> str:
    segments = [
        value
        for value in (
            os.getenv("GITHUB_RUN_ID", "").strip(),
            os.getenv("GITHUB_RUN_ATTEMPT", "").strip(),
            os.getenv("GITHUB_JOB", "").strip(),
            uuid4().hex[:8],
        )
        if value
    ]
    token = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9-]", "-", "-".join(segments))).strip("-")
    if not token:
        token = uuid4().hex[:16]
    if len(token) > 48:
        token = token[:48].rstrip("-")
    return token


def _generated_service_name(prefix: str, token: str) -> str:
    normalized_prefix = re.sub(r"[^A-Za-z0-9]", "", prefix)
    if not normalized_prefix:
        msg = "The service name prefix must contain at least one letter or number."
        raise ValueError(msg)

    minimum_token_length = 8
    max_name_length = 32
    max_prefix_length = max_name_length - minimum_token_length
    if len(normalized_prefix) > max_prefix_length:
        msg = (
            f"The service name prefix '{prefix}' is too long. Leave at least "
            f"{minimum_token_length} characters for the unique suffix so the final "
            "Squid service name stays within Squid's 32-character limit."
        )
        raise ValueError(msg)

    normalized_token = re.sub(r"[^A-Za-z0-9]", "", token) or uuid4().hex
    max_token_length = max_name_length - len(normalized_prefix)
    if len(normalized_token) > max_token_length:
        normalized_token = normalized_token[-max_token_length:]

    return validate_service_name(
        f"{normalized_prefix}{normalized_token}",
        parameter_name="GeneratedServiceName",
    )


def _combined_process_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part is not None and part.strip()
    )


def _run_msiexec(
    arguments: tuple[str, ...],
    *,
    log_path: Path | None = None,
    acceptable_exit_codes: tuple[int, ...] = (0,),
) -> int:
    effective_arguments = list(arguments)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        effective_arguments.extend(("/L*V", os.fspath(log_path)))

    completed = subprocess.run(
        ("msiexec.exe", *effective_arguments),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in acceptable_exit_codes:
        log_hint = f" See {log_path}." if log_path is not None else ""
        output = _combined_process_output(completed)
        msg = (
            f"msiexec.exe {' '.join(effective_arguments)} failed with exit code "
            f"{completed.returncode}.{log_hint}"
        )
        if output:
            msg = f"{msg} Output: {output}"
        raise RuntimeError(msg)

    return completed.returncode


def _run_sc(
    arguments: tuple[str, ...],
    *,
    acceptable_exit_codes: tuple[int, ...] = (0,),
) -> str:
    completed = subprocess.run(
        (_system_sc_executable(), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )
    output = _combined_process_output(completed)
    if completed.returncode not in acceptable_exit_codes:
        msg = f"sc.exe {' '.join(arguments)} failed with exit code {completed.returncode}."
        if output:
            msg = f"{msg} Output: {output}"
        raise RuntimeError(msg)

    return output


def _system_sc_executable() -> str:
    system_root = os.getenv("SystemRoot", "").strip()
    if system_root:
        candidate = Path(system_root) / "System32" / "sc.exe"
        if candidate.is_file():
            return os.fspath(candidate)
    return "sc.exe"


def _query_service(name: str) -> tuple[bool, str | None]:
    completed = subprocess.run(
        (_system_sc_executable(), "query", name),
        text=True,
        capture_output=True,
        check=False,
    )
    output = _combined_process_output(completed)
    if completed.returncode == 1060 or "FAILED 1060" in output.upper():
        return False, None
    if completed.returncode != 0:
        msg = f"sc.exe query {name} failed with exit code {completed.returncode}."
        if output:
            msg = f"{msg} Output: {output}"
        raise RuntimeError(msg)

    match = re.search(r"STATE\s*:\s*\d+\s+([A-Z_]+)", output)
    if match is None:
        msg = f"Unable to parse the service state for '{name}' from sc.exe query output."
        raise RuntimeError(msg)

    return True, match.group(1)


# Squid's native Windows service code keys ConfigFile/CommandLine beneath
# PACKAGE_NAME, which is currently "Squid Web Proxy".
_SQUID_SERVICE_REGISTRY_PRODUCT_NAME = "Squid Web Proxy"


def _service_registry_path(name: str) -> str:
    return rf"SOFTWARE\squid-cache.org\{_SQUID_SERVICE_REGISTRY_PRODUCT_NAME}\{name}"


def _service_registry_values(name: str) -> dict[str, str]:
    if os.name != "nt":
        return {}

    import winreg

    values: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _service_registry_path(name)) as handle:
            for value_name in ("ConfigFile", "CommandLine"):
                try:
                    value, _ = winreg.QueryValueEx(handle, value_name)
                except FileNotFoundError:
                    continue
                if isinstance(value, str) and value:
                    values[value_name] = value
    except FileNotFoundError:
        return {}

    return values


def _normalized_windows_path_text(path_text: str) -> str:
    return os.path.normcase(os.path.normpath(path_text))


def _command_line_config_path(command_line: str) -> str | None:
    match = re.search(r'(?:^|\s)-f\s+(?:"([^"]+)"|(\S+))', command_line)
    if match is None:
        return None

    quoted_path, unquoted_path = match.groups()
    return quoted_path or unquoted_path


def _service_timeout_diagnostics(
    name: str,
    *,
    last_observed_status: str | None,
    install_root: Path | None = None,
) -> str:
    diagnostics: list[str] = []
    if last_observed_status is not None:
        diagnostics.append(f"Last observed service status: {last_observed_status}")

    for arguments, label in (
        (("queryex", name), "sc.exe queryex"),
        (("qc", name), "sc.exe qc"),
    ):
        try:
            output = _run_sc(arguments)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(f"{label} failed: {exc}")
            continue

        normalized_output = " | ".join(line.strip() for line in output.splitlines() if line.strip())
        diagnostics.append(f"{label}: {normalized_output}")

    registry_path = rf"HKLM\{_service_registry_path(name)}"
    registry_values = _service_registry_values(name)
    if registry_values:
        normalized_registry_values = " | ".join(
            f"{key}={value}" for key, value in registry_values.items()
        )
        diagnostics.append(
            f"Squid service registry values ({registry_path}): {normalized_registry_values}"
        )
    else:
        diagnostics.append(f"Squid service registry values are unavailable at {registry_path}")

    if install_root is not None:
        runtime_paths = (
            ("Resolved install root", install_root),
            ("Materialized config", install_root / "etc" / "squid.conf"),
            ("PID file", install_root / "var" / "run" / "squid.pid"),
            ("Cache log", install_root / "var" / "logs" / "cache.log"),
            ("Access log", install_root / "var" / "logs" / "access.log"),
            ("Squid stderr log", install_root / "sbin" / "squid.exe.log"),
        )
        for label, path in runtime_paths:
            diagnostics.append(f"{label} exists: {path.exists()} ({path})")

        for label, path in (
            ("Cache log tail", install_root / "var" / "logs" / "cache.log"),
            ("Access log tail", install_root / "var" / "logs" / "access.log"),
            ("Squid stderr log tail", install_root / "sbin" / "squid.exe.log"),
        ):
            tail = _tail_text_file(path)
            if tail:
                diagnostics.append(f"{label}:\n{tail}")

    return "\n".join(diagnostics)


def _wait_service_registration_state(
    name: str,
    *,
    present: bool,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        registered, _ = _query_service(name)
        if registered is present:
            return
        time.sleep(1)

    expected_state = "visible" if present else "absent"
    msg = (
        f"The Squid Windows service '{name}' did not become {expected_state} within "
        f"{timeout_seconds} seconds."
    )
    raise RuntimeError(msg)


def _wait_service_status(
    name: str,
    *,
    desired_status: str,
    timeout_seconds: int,
    install_root: Path | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_observed_status: str | None = None
    while time.monotonic() < deadline:
        registered, status = _query_service(name)
        if not registered:
            msg = f"The Squid Windows service '{name}' is not registered."
            raise RuntimeError(msg)
        last_observed_status = status
        if status == desired_status:
            return
        time.sleep(1)

    diagnostics = _service_timeout_diagnostics(
        name,
        last_observed_status=last_observed_status,
        install_root=install_root,
    )
    if diagnostics:
        get_logger("squid4win").error(
            "Service status diagnostics for '%s' after waiting for '%s':\n%s",
            name,
            desired_status,
            diagnostics,
        )

    msg = (
        f"The Squid Windows service '{name}' did not reach status '{desired_status}' "
        f"within {timeout_seconds} seconds."
    )
    if last_observed_status is not None:
        msg = f"{msg} Last observed status: {last_observed_status}."
    raise RuntimeError(msg)


def _stop_service_if_present(name: str, *, timeout_seconds: int) -> bool:
    registered, status = _query_service(name)
    if not registered:
        return False
    if status == "STOPPED":
        return False
    if status == "STOP_PENDING":
        _wait_service_status(name, desired_status="STOPPED", timeout_seconds=timeout_seconds)
        return True

    _run_sc(("stop", name), acceptable_exit_codes=(0, 1062))
    _wait_service_status(name, desired_status="STOPPED", timeout_seconds=timeout_seconds)
    return True


def _start_service(
    name: str,
    *,
    timeout_seconds: int,
    install_root: Path | None = None,
) -> None:
    _run_sc(("start", name), acceptable_exit_codes=(0, 1056))
    _wait_service_status(
        name,
        desired_status="RUNNING",
        timeout_seconds=timeout_seconds,
        install_root=install_root,
    )


def _service_command_line(name: str) -> str:
    output = _run_sc(("qc", name))
    match = re.search(r"BINARY_PATH_NAME\s*:\s*(.+)", output)
    if match is None:
        msg = f"Unable to parse the service command line for '{name}'."
        raise RuntimeError(msg)

    return match.group(1).strip()


def _invoke_service_helper_uninstall(install_root: Path, *, service_name: str) -> bool:
    service_helper_path = install_root / "installer" / "svc.ps1"
    if not service_helper_path.is_file():
        return False

    completed = subprocess.run(
        (
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            os.fspath(service_helper_path),
            "-Action",
            "Uninstall",
            "-InstallRoot",
            os.fspath(install_root),
            "-ServiceName",
            service_name,
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        output = _combined_process_output(completed)
        msg = (
            f"The installed service helper failed while uninstalling '{service_name}' "
            f"from '{install_root}'."
        )
        if output:
            msg = f"{msg} Output: {output}"
        raise RuntimeError(msg)

    return True


def _best_effort_service_validation_cleanup(
    *,
    install_root: Path,
    service_name: str,
    msi_path: Path | None,
    install_attempted: bool,
    uninstall_completed: bool,
    timeout_seconds: int,
) -> CleanupResult:
    actions: list[str] = []
    issues: list[str] = []

    if (
        install_attempted
        and not uninstall_completed
        and msi_path is not None
        and msi_path.is_file()
    ):
        try:
            _run_msiexec(
                ("/x", os.fspath(msi_path), "/qn", "/norestart"),
                acceptable_exit_codes=(0, 1605, 1614),
            )
            actions.append("Requested MSI uninstall during cleanup.")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"MSI cleanup uninstall failed: {exc}")

    try:
        if _stop_service_if_present(service_name, timeout_seconds=timeout_seconds):
            actions.append(f"Stopped leftover service '{service_name}'.")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Stopping leftover service '{service_name}' failed: {exc}")

    try:
        registered, _ = _query_service(service_name)
        if registered and install_root.is_dir():
            if _invoke_service_helper_uninstall(install_root, service_name=service_name):
                _wait_service_registration_state(
                    service_name,
                    present=False,
                    timeout_seconds=timeout_seconds,
                )
                actions.append(f"Invoked installer helper cleanup for '{service_name}'.")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Installer helper cleanup for '{service_name}' failed: {exc}")

    try:
        registered, _ = _query_service(service_name)
        if registered:
            _stop_service_if_present(service_name, timeout_seconds=timeout_seconds)
            _run_sc(("delete", service_name))
            _wait_service_registration_state(
                service_name,
                present=False,
                timeout_seconds=timeout_seconds,
            )
            actions.append(f"Deleted leftover service '{service_name}' with sc.exe.")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Final service deletion for '{service_name}' failed: {exc}")

    try:
        registered, _ = _query_service(service_name)
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Checking leftover service '{service_name}' failed: {exc}")
        registered = False
    if registered:
        issues.append(
            f"The Squid Windows service '{service_name}' is still registered after cleanup."
        )

    if install_root.exists():
        try:
            _remove_tree(install_root)
            actions.append(f"Removed isolated install root '{install_root}'.")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"Removing isolated install root '{install_root}' failed: {exc}")

    return CleanupResult(actions=tuple(actions), issues=tuple(issues))


def _default_service_validation_install_root(validation_token: str) -> Path:
    return (
        Path(os.getenv("ProgramData", r"C:\ProgramData"))
        / "Squid4Win"
        / "service-validation"
        / validation_token
        / "installed"
    )


def _capture_service_validation_install_root(
    *,
    install_root: Path,
    validation_root: Path,
) -> Path | None:
    if not install_root.is_dir():
        return None

    snapshot_root = validation_root / "installed-root"
    _remove_tree(snapshot_root)
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(install_root, snapshot_root, dirs_exist_ok=True)
    return snapshot_root


def _write_service_runner_validation_summary(
    result: ServiceRunnerValidationResult,
    *,
    status: str,
    failure_message: str | None,
) -> None:
    summary_lines = [
        "## Service runner validation",
        "",
        f"- Status: `{status}`",
        f"- Service name: `{result.service_name}`",
        f"- Validation root: `{result.validation_root}`",
        f"- Install root: `{result.install_root}`",
        f"- MSI: `{result.msi_path}`",
    ]
    if result.service_command_line is not None:
        summary_lines.append(f"- Service command line: `{result.service_command_line}`")
    if result.cleanup_actions:
        summary_lines.append(f"- Cleanup actions: `{' ; '.join(result.cleanup_actions)}`")
    if result.cleanup_issues:
        summary_lines.append(f"- Cleanup issues: `{' ; '.join(result.cleanup_issues)}`")
    if failure_message is not None:
        summary_lines.append(f"- Failure: `{failure_message}`")

    append_step_summary("\n".join(summary_lines) + "\n")


def run_service_runner_validation(
    options: ServiceRunnerValidationOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    logger = get_logger("squid4win")
    paths = RepositoryPaths.discover(options.repository_root)
    build_root = _resolved_or_default(
        options.build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    artifact_base_root = _resolved_or_default(
        options.artifact_root,
        paths.artifact_root,
        base=paths.repository_root,
    )
    validation_token = _validation_token()
    service_name = (
        options.service_name
        if options.service_name is not None
        else _generated_service_name(options.service_name_prefix, validation_token)
    )
    validation_root = artifact_base_root / "service-validation" / validation_token
    install_root = _resolved_or_default(
        options.install_root,
        _default_service_validation_install_root(validation_token),
        base=paths.repository_root,
    )

    if not execute:
        logger.info(
            "The Python automation will validate the MSI-installed service using '%s' "
            "and the temporary service name '%s'.",
            validation_root,
            service_name,
        )
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to validate the installed service lifecycle."
        )

    _assert_runner_validation_prerequisites(
        allow_non_runner_execution=options.allow_non_runner_execution
    )

    bundle_options = BundlePackageOptions(
        repository_root=paths.repository_root,
        configuration=options.configuration,
        build_root=build_root,
        artifact_root=validation_root,
        require_tray=options.require_tray,
        require_notices=options.require_notices,
        build_installer=True,
        service_name=service_name,
        dependency_sources=options.dependency_sources,
    )

    caught_error: Exception | None = None
    cleanup_result = CleanupResult(actions=(), issues=())
    bundle_state: BundlePackageState | None = None
    msi_path: Path | None = None
    service_command_line: str | None = None
    install_attempted = False
    uninstall_completed = False

    try:
        validation_root.mkdir(parents=True, exist_ok=True)
        if install_root.exists():
            _remove_tree(install_root)

        run_bundle_package(bundle_options, runner, execute=True)
        bundle_state = BundlePackageState.inspect(
            paths.repository_root,
            build_root,
            options.configuration,
            squid_stage_root=build_root / "install" / options.configuration.value.lower(),
            artifact_root=validation_root,
            installer_project_path=paths.installer_project_path,
        )
        staged_payload_root = bundle_state.installer_payload_root
        expected_staged_paths = (
            staged_payload_root / "installer" / "svc.ps1",
            staged_payload_root / "installer" / "Assert-SquidServiceName.ps1",
            staged_payload_root / "etc" / "squid.conf.template",
        )
        for expected_path in expected_staged_paths:
            if not expected_path.exists():
                msg = f"The staged payload '{staged_payload_root}' is missing '{expected_path}'."
                raise FileNotFoundError(msg)

        staged_config_path = staged_payload_root / "etc" / "squid.conf"
        if staged_config_path.exists():
            msg = (
                f"The staged payload already contains '{staged_config_path}'. The installer "
                "contract requires shipping squid.conf.template and materializing squid.conf "
                "during install."
            )
            raise RuntimeError(msg)

        msi_path = bundle_state.msi_path
        install_attempted = True
        logger.info(
            "Installing %s to %s using temporary service name '%s'.",
            msi_path,
            install_root,
            service_name,
        )
        _run_msiexec(
            (
                "/i",
                os.fspath(msi_path),
                "/qn",
                "/norestart",
                f"INSTALLFOLDER={install_root}",
            ),
            log_path=validation_root / "msi-install.log",
        )

        expected_installed_paths = (
            install_root / "installer" / "svc.ps1",
            install_root / "installer" / "Assert-SquidServiceName.ps1",
            install_root / "etc" / "squid.conf",
            install_root / "var" / "cache",
            install_root / "var" / "logs",
            install_root / "var" / "run",
        )
        for expected_path in expected_installed_paths:
            if not expected_path.exists():
                msg = f"Expected installed path '{expected_path}' was not created by the MSI."
                raise FileNotFoundError(msg)

        _wait_service_registration_state(
            service_name,
            present=True,
            timeout_seconds=options.service_timeout_seconds,
        )
        registry_path = rf"HKLM\{_service_registry_path(service_name)}"
        expected_registry_config_path = os.fspath(install_root / "etc" / "squid.conf")
        registry_values = _service_registry_values(service_name)
        actual_registry_config_path = registry_values.get("ConfigFile")
        if actual_registry_config_path is None:
            msg = (
                f"The installed service registry key '{registry_path}' did not contain "
                "a ConfigFile value."
            )
            raise RuntimeError(msg)
        if _normalized_windows_path_text(
            actual_registry_config_path
        ) != _normalized_windows_path_text(expected_registry_config_path):
            msg = (
                f"The installed service registry key '{registry_path}' stored ConfigFile="
                f"'{actual_registry_config_path}', expected '{expected_registry_config_path}'."
            )
            raise RuntimeError(msg)
        actual_registry_command_line = registry_values.get("CommandLine")
        if actual_registry_command_line is None:
            msg = (
                f"The installed service registry key '{registry_path}' did not contain "
                "a CommandLine value."
            )
            raise RuntimeError(msg)
        registry_command_line_config_path = _command_line_config_path(actual_registry_command_line)
        if registry_command_line_config_path is None:
            msg = (
                f"The installed service registry key '{registry_path}' stored CommandLine="
                f"'{actual_registry_command_line}', which did not contain '-f <config>'."
            )
            raise RuntimeError(msg)
        if _normalized_windows_path_text(
            registry_command_line_config_path
        ) != _normalized_windows_path_text(expected_registry_config_path):
            msg = (
                f"The installed service registry key '{registry_path}' stored CommandLine="
                f"'{actual_registry_command_line}', expected it to reference "
                f"'{expected_registry_config_path}'."
            )
            raise RuntimeError(msg)
        logger.info(
            "Validated Squid service registry values for '%s' at %s: ConfigFile=%s; CommandLine=%s",
            service_name,
            registry_path,
            actual_registry_config_path,
            actual_registry_command_line,
        )
        service_command_line = _service_command_line(service_name)
        if service_name not in service_command_line:
            msg = (
                "The installed service command line did not reference the temporary "
                f"service name '{service_name}': {service_command_line}"
            )
            raise RuntimeError(msg)

        _start_service(
            service_name,
            timeout_seconds=options.service_timeout_seconds,
            install_root=install_root,
        )
        _stop_service_if_present(service_name, timeout_seconds=options.service_timeout_seconds)
        _run_msiexec(
            ("/x", os.fspath(msi_path), "/qn", "/norestart"),
            log_path=validation_root / "msi-uninstall.log",
        )
        uninstall_completed = True
        _wait_service_registration_state(
            service_name,
            present=False,
            timeout_seconds=options.service_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        caught_error = exc
        try:
            snapshot_root = _capture_service_validation_install_root(
                install_root=install_root,
                validation_root=validation_root,
            )
            if snapshot_root is not None:
                logger.info(
                    "Captured installed service validation tree at %s before cleanup.",
                    snapshot_root,
                )
        except Exception as snapshot_exc:  # noqa: BLE001
            logger.warning(
                "Capturing the installed service validation tree from %s failed: %s",
                install_root,
                snapshot_exc,
            )
    finally:
        cleanup_result = _best_effort_service_validation_cleanup(
            install_root=install_root,
            service_name=service_name,
            msi_path=msi_path,
            install_attempted=install_attempted,
            uninstall_completed=uninstall_completed,
            timeout_seconds=options.service_timeout_seconds,
        )
        result = ServiceRunnerValidationResult(
            validation_root=validation_root,
            install_root=install_root,
            msi_path=msi_path,
            service_name=service_name,
            service_command_line=service_command_line,
            cleanup_actions=cleanup_result.actions,
            cleanup_issues=cleanup_result.issues,
        )
        _write_service_runner_validation_summary(
            result,
            status="passed" if caught_error is None and cleanup_result.clean else "failed",
            failure_message=None if caught_error is None else str(caught_error),
        )

    if caught_error is not None:
        raise caught_error
    if not cleanup_result.clean:
        msg = f"Service runner validation cleanup failed: {'; '.join(cleanup_result.issues)}"
        raise RuntimeError(msg)
    if bundle_state is None or msi_path is None:
        msg = "Service runner validation did not produce the expected MSI artifact."
        raise RuntimeError(msg)

    logger.info("Service runner validation passed for %s.", msi_path)
    return 0


def run_conan_recipe_validation(
    options: ConanRecipeValidationOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    paths = RepositoryPaths.discover(options.repository_root)
    resolved_host_profile_path = _resolved_recipe_validation_profile_path(
        paths,
        options.host_profile_path,
    )
    plan = build_conan_recipe_validation_plan(options)
    if not execute:
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to validate the Squid recipe with conan create."
        )

    if shutil.which("conan") is None:
        msg = "The conan CLI is not available on PATH. Run uv sync first."
        raise FileNotFoundError(msg)
    if not resolved_host_profile_path.is_file():
        msg = f"The Conan host profile '{resolved_host_profile_path}' does not exist."
        raise FileNotFoundError(msg)

    paths.conan_home_path.mkdir(parents=True, exist_ok=True)
    runner.run(plan)
    return 0


def run_conan_lockfile_update(
    options: ConanLockfileUpdateOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    context = _resolve_conan_context(
        options.repository_root,
        options.build_root,
        options.configuration,
        options.host_profile_path,
        options.lockfile_path,
        options.dependency_sources,
    )
    plan = build_conan_lockfile_update_plan(options)
    if not execute:
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to refresh the selected Conan lockfile."
        )

    if shutil.which("conan") is None:
        msg = "The conan CLI is not available on PATH. Run uv sync first."
        raise FileNotFoundError(msg)

    context.paths.conan_home_path.mkdir(parents=True, exist_ok=True)
    context.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
    runner.run(plan)
    return 0


def run_bundle_package(
    options: BundlePackageOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    logger = get_logger("squid4win")
    paths = RepositoryPaths.discover(options.repository_root)
    build_root = _resolved_or_default(
        options.build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    if options.squid_stage_root is not None and options.build_root is None:
        explicit_stage_root = resolve_path(options.squid_stage_root, base=paths.repository_root)
        if explicit_stage_root is not None:
            inferred_build_root = _infer_build_root_from_stage_root(
                explicit_stage_root,
                options.configuration,
            )
            if inferred_build_root is not None:
                build_root = inferred_build_root

    artifact_root = _resolved_or_default(
        options.artifact_root,
        paths.artifact_root,
        base=paths.repository_root,
    )
    squid_stage_root = _resolved_or_default(
        options.squid_stage_root,
        build_root / "install" / options.configuration.value.lower(),
        base=paths.repository_root,
    )
    installer_project_path = _resolved_or_default(
        options.installer_project_path,
        paths.installer_project_path,
        base=paths.repository_root,
    )
    bundle_state = BundlePackageState.inspect(
        paths.repository_root,
        build_root,
        options.configuration,
        squid_stage_root=squid_stage_root,
        artifact_root=artifact_root,
        installer_project_path=installer_project_path,
    )
    prerequisite_reasons = _bundle_prerequisite_reasons(options, bundle_state=bundle_state)
    buildable_stage_root = build_root / "install" / options.configuration.value.lower()
    if prerequisite_reasons and squid_stage_root != buildable_stage_root:
        msg = (
            "bundle-package can only materialize missing prerequisites when "
            "--squid-stage-root matches '<build-root>\\install\\<configuration>'. "
            f"Expected '{buildable_stage_root}', but received '{squid_stage_root}'."
        )
        raise ValueError(msg)

    if options.build_installer and not installer_project_path.is_file():
        msg = f"Installer project '{installer_project_path}' does not exist."
        raise FileNotFoundError(msg)

    plan = build_bundle_plan(options)
    if not execute:
        if prerequisite_reasons:
            logger.info(
                "The bundle prerequisites are incomplete (%s). The Python automation will "
                "materialize them first.",
                "; ".join(prerequisite_reasons),
            )
            if _bundle_requires_tray(options):
                tray_plan = build_tray_plan(
                    TrayBuildOptions(
                        repository_root=paths.repository_root,
                        configuration=options.configuration,
                        build_root=build_root,
                    )
                )
                runner.describe(tray_plan)
        logger.info(
            "The Python automation will mirror '%s' into '%s'.",
            squid_stage_root,
            bundle_state.installer_payload_root,
        )
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to stage the payload and optional "
            "installer artifacts."
        )

    if prerequisite_reasons:
        run_squid_build(
            SquidBuildOptions(
                repository_root=paths.repository_root,
                configuration=options.configuration,
                build_root=build_root,
                with_tray=_bundle_requires_tray(options),
                with_runtime_dlls=True,
                with_packaging_support=True,
                dependency_sources=options.dependency_sources,
            ),
            runner,
            execute=True,
        )
        bundle_state = BundlePackageState.inspect(
            paths.repository_root,
            build_root,
            options.configuration,
            squid_stage_root=squid_stage_root,
            artifact_root=artifact_root,
            installer_project_path=installer_project_path,
        )

    install_payload_root = bundle_state.installer_payload_root
    artifact_root.mkdir(parents=True, exist_ok=True)
    _remove_tree(install_payload_root)
    install_payload_root.mkdir(parents=True, exist_ok=True)
    _copy_directory_contents(bundle_state.squid_stage_root, install_payload_root)

    tray_executable_path = install_payload_root / _TRAY_EXECUTABLE_NAME
    if _bundle_requires_tray(options) and not tray_executable_path.is_file():
        msg = f"Expected the staged tray executable at '{tray_executable_path}'."
        raise FileNotFoundError(msg)

    squid_candidates = (
        install_payload_root / "sbin" / "squid.exe",
        install_payload_root / "bin" / "squid.exe",
    )
    staged_squid_executable_path = next(
        (candidate for candidate in squid_candidates if candidate.is_file()),
        None,
    )
    if staged_squid_executable_path is None:
        msg = f"Expected squid.exe under '{install_payload_root}'."
        raise FileNotFoundError(msg)

    notices_path = install_payload_root / "THIRD-PARTY-NOTICES.txt"
    if _bundle_requires_notices(options) and not notices_path.is_file():
        msg = f"Expected THIRD-PARTY-NOTICES.txt under '{install_payload_root}'."
        raise FileNotFoundError(msg)

    if options.sign_payload_files:
        _run_invocation(
            runner,
            paths.repository_root,
            name="sign-payload",
            invocation=_signing_invocation(
                paths,
                target_path=install_payload_root,
                recurse=True,
                description="Sign the staged payload files in the install root.",
            ),
        )

    if options.create_portable_zip:
        _compress_directory_contents(install_payload_root, bundle_state.portable_zip_path)

    if options.build_installer:
        product_version = options.product_version or _derive_installer_version(
            paths.squid_release_metadata_path
        )
        project_directory = installer_project_path.parent
        configuration_output_root = project_directory / "bin" / options.configuration.value
        configuration_intermediate_root = project_directory / "obj" / options.configuration.value
        for path_to_clear in (configuration_output_root, configuration_intermediate_root):
            _remove_tree(path_to_clear)

        _run_invocation(
            runner,
            paths.repository_root,
            name="build-installer",
            invocation=ProcessInvocation(
                description="Build the WiX installer project from the staged payload.",
                command=(
                    "dotnet",
                    "build",
                    str(installer_project_path),
                    "-c",
                    options.configuration.value,
                    "-t:Rebuild",
                    "--nologo",
                    f"-p:InstallerPayloadRoot={install_payload_root}",
                    f"-p:ProductVersion={product_version}",
                    f"-p:SquidServiceName={options.service_name}",
                ),
            ),
        )

        built_msi = next(
            (
                path
                for path in sorted(
                    project_directory.joinpath("bin").rglob("*.msi"),
                    key=lambda candidate: candidate.stat().st_mtime,
                    reverse=True,
                )
            ),
            None,
        )
        if built_msi is None:
            msg = f"Unable to locate the built MSI under '{project_directory / 'bin'}'."
            raise FileNotFoundError(msg)

        shutil.copy2(built_msi, bundle_state.msi_path)
        if options.sign_msi:
            _run_invocation(
                runner,
                paths.repository_root,
                name="sign-msi",
                invocation=_signing_invocation(
                    paths,
                    target_path=bundle_state.msi_path,
                    recurse=False,
                    description="Sign the built MSI artifact.",
                ),
            )

    logger.info("Installer payload root ready at %s.", install_payload_root)
    return 0
