from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml

from squid4win.logging_utils import get_logger
from squid4win.models import (
    AutomationPlan,
    BuildConfiguration,
    BundlePackageOptions,
    BundlePackageState,
    ConanLockfileUpdateOptions,
    ProcessInvocation,
    RepositoryPaths,
    SquidBuildLayout,
    SquidBuildOptions,
    TrayBuildLayout,
    TrayBuildOptions,
)
from squid4win.paths import resolve_path

if TYPE_CHECKING:
    from squid4win.runner import PlanRunner


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


def _bool_text(enabled: bool) -> str:
    return str(enabled).lower()


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


def _load_build_settings(paths: RepositoryPaths) -> dict[str, Any]:
    loaded = yaml.safe_load(paths.conan_data_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        msg = f"Expected a mapping in '{paths.conan_data_path}'."
        raise ValueError(msg)

    build_settings = loaded.get("build") or {}
    if not isinstance(build_settings, dict):
        msg = f"Expected a top-level 'build' mapping in '{paths.conan_data_path}'."
        raise ValueError(msg)

    return cast(dict[str, Any], build_settings)


def _recipe_option_arguments(
    paths: RepositoryPaths,
    *,
    with_tray: bool,
    with_runtime_dlls: bool,
    with_packaging_support: bool,
) -> list[str]:
    arguments = [
        "-o",
        f"&:with_tray={_bool_text(with_tray)}",
        "-o",
        f"&:with_runtime_dlls={_bool_text(with_runtime_dlls)}",
        "-o",
        f"&:with_packaging_support={_bool_text(with_packaging_support)}",
    ]

    build_settings = _load_build_settings(paths)
    msys2_settings = build_settings.get("msys2") or {}
    if isinstance(msys2_settings, dict):
        packages = _string_list(msys2_settings.get("packages", []))
        if packages:
            arguments.extend(
                ["-o:b", f"msys2/*:additional_packages={','.join(packages)}"]
            )

    mingw_settings = build_settings.get("mingw_builds") or {}
    if isinstance(mingw_settings, dict):
        for option_name in ("threads", "exception", "runtime"):
            option_value = str(mingw_settings.get(option_name, "")).strip()
            if option_value:
                arguments.extend(["-o:b", f"mingw-builds/*:{option_name}={option_value}"])

    return arguments


def _base_conan_environment(paths: RepositoryPaths) -> dict[str, str]:
    return {"CONAN_HOME": str(paths.conan_home_path)}


def _description_suffix(options: SquidBuildOptions) -> str:
    if options.bootstrap_only:
        return "Bootstrap the repo-local Conan workspace."

    return (
        "Detect the Conan profile, refresh the lockfile when needed, source the "
        "root recipe, and build the staged native Squid bundle."
    )


def _resolve_conan_context(
    repository_root: Path | None,
    build_root: Path | None,
    configuration: BuildConfiguration,
    host_profile_path: Path | None,
    lockfile_path: Path | None,
) -> ConanContext:
    paths = RepositoryPaths.discover(repository_root)
    resolved_build_root = _resolved_or_default(
        build_root,
        paths.build_root,
        base=paths.repository_root,
    )
    layout = SquidBuildLayout.create(paths.repository_root, resolved_build_root, configuration)
    resolved_host_profile_path = _resolved_or_default(
        host_profile_path,
        paths.conan_root / "profiles" / "msys2-mingw-x64",
        base=paths.repository_root,
    )
    resolved_lockfile_path = (
        resolve_path(lockfile_path, base=paths.repository_root) or layout.repo_lockfile_path
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
    numeric_parts = [int(part) for part in re.split(r"[^0-9]+", raw_version) if part]
    if not numeric_parts:
        msg = f"Unable to derive an installer version from '{raw_version}'."
        raise ValueError(msg)

    normalized_parts = numeric_parts[:3]
    while len(normalized_parts) < 3:
        normalized_parts.append(0)

    revision = 0
    raw_run_number = os.getenv("GITHUB_RUN_NUMBER", "").strip()
    if raw_run_number.isdigit():
        revision = min(int(raw_run_number), 65535)

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
            handle.write(
                f"started_at={datetime.now(UTC).isoformat(timespec='seconds')}\n"
            )
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
    )
    recipe_option_arguments = _recipe_option_arguments(
        context.paths,
        with_tray=options.with_tray,
        with_runtime_dlls=options.with_runtime_dlls,
        with_packaging_support=options.with_packaging_support,
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
                    description="Refresh the Conan lockfile for the root Squid recipe.",
                    command=(
                        "conan",
                        "lock",
                        "create",
                        str(context.paths.repository_root),
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
                        "--build=missing",
                        *recipe_option_arguments,
                    ),
                    environment=base_environment,
                )
            )

        commands.append(
            ProcessInvocation(
                description="Resolve the root Conan recipe source tree.",
                command=("conan", "source", str(context.paths.repository_root)),
                environment=base_environment,
            )
        )

        build_environment = {
            **base_environment,
            "SQUID4WIN_MAKE_JOBS": str(options.make_jobs),
        }
        if options.additional_configure_args:
            build_environment["SQUID4WIN_CONFIGURE_ARGS_JSON"] = json.dumps(
                list(options.additional_configure_args)
            )
        if options.with_tray:
            tray_context = _resolve_tray_context(
                TrayBuildOptions(
                    repository_root=context.paths.repository_root,
                    configuration=options.configuration,
                    build_root=context.build_root,
                )
            )
            build_environment["SQUID4WIN_TRAY_PACKAGE_ROOT"] = str(tray_context.package_root)

        commands.append(
            ProcessInvocation(
                description="Build the staged native Squid bundle with the root Conan recipe.",
                command=(
                    "conan",
                    "build",
                    str(context.paths.repository_root),
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
                    "--build=missing",
                    *recipe_option_arguments,
                ),
                environment=build_environment,
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


def build_conan_lockfile_update_plan(options: ConanLockfileUpdateOptions) -> AutomationPlan:
    context = _resolve_conan_context(
        options.repository_root,
        options.build_root,
        options.configuration,
        options.host_profile_path,
        options.lockfile_path,
    )
    recipe_option_arguments = _recipe_option_arguments(
        context.paths,
        with_tray=options.with_tray,
        with_runtime_dlls=options.with_runtime_dlls,
        with_packaging_support=options.with_packaging_support,
    )
    base_environment = _base_conan_environment(context.paths)

    return AutomationPlan(
        name="conan-lockfile-update",
        summary="Detect the Conan profile and refresh the committed lockfile.",
        repository_root=context.paths.repository_root,
        commands=(
            ProcessInvocation(
                description="Detect the Conan default profile for the repo-local CONAN_HOME.",
                command=("conan", "profile", "detect", "--force"),
                environment=base_environment,
            ),
            ProcessInvocation(
                description="Refresh the Conan lockfile for the root Squid recipe.",
                command=(
                    "conan",
                    "lock",
                    "create",
                    str(context.paths.repository_root),
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
                    "--build=missing",
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

    published_tray_executable_path = context.publish_root / "Squid4Win.Tray.exe"
    if not published_tray_executable_path.is_file():
        msg = f"Expected the published tray executable at '{published_tray_executable_path}'."
        raise FileNotFoundError(msg)

    _copy_directory_contents(context.publish_root, context.package_root / "bin")
    shutil.copy2(context.license_path, context.package_root / "licenses" / "LICENSE")
    manifest_path = _harvest_tray_notice_manifest(context.publish_root, context.package_root)

    packaged_tray_executable_path = context.package_root / "bin" / "Squid4Win.Tray.exe"
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
            source_root = context.paths.repository_root / "sources" / (
                f"squid-{release_metadata['version']}"
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

    if not options.bootstrap_only and not context.layout.stage_root.is_dir():
        msg = (
            "The Conan build finished without materializing the staged bundle at "
            f"'{context.layout.stage_root}'."
        )
        raise FileNotFoundError(msg)

    if not options.bootstrap_only:
        logger.info("Staged native bundle ready at %s.", context.layout.stage_root)
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
    )
    plan = build_conan_lockfile_update_plan(options)
    if not execute:
        runner.describe(plan)
        return _log_dry_run_footer(
            "Dry-run only. Re-run with --execute to refresh the committed Conan lockfile."
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

    tray_executable_path = install_payload_root / "Squid4Win.Tray.exe"
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
