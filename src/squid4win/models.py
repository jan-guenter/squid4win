from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from squid4win.paths import discover_repository_root

_DEFAULT_REPOSITORY = "jan-guenter/squid4win"
_REPOSITORY_PATTERN = r"[^/]+/[^/]+"
_REPOSITORY_FORMAT_MESSAGE = "Repository values must follow the owner/name format."
_TRAY_EXECUTABLE_NAME = "Squid4Win.Tray.exe"


class BuildConfiguration(StrEnum):
    DEBUG = "Debug"
    RELEASE = "Release"


class DependencySource(StrEnum):
    SYSTEM = "system"
    CONAN = "conan"


class ConanDependencyLinkage(StrEnum):
    DEFAULT = "default"
    SHARED = "shared"
    STATIC = "static"

    def as_shared_option(self) -> bool | None:
        if self is ConanDependencyLinkage.DEFAULT:
            return None
        return self is ConanDependencyLinkage.SHARED


class NativeDependencySourceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    openssl_source: DependencySource = DependencySource.SYSTEM
    libxml2_source: DependencySource = DependencySource.SYSTEM
    pcre2_source: DependencySource = DependencySource.SYSTEM
    zlib_source: DependencySource = DependencySource.SYSTEM

    def as_option_values(self) -> dict[str, str]:
        return {
            "openssl_source": self.openssl_source.value,
            "libxml2_source": self.libxml2_source.value,
            "pcre2_source": self.pcre2_source.value,
            "zlib_source": self.zlib_source.value,
        }


def default_make_jobs() -> int:
    cpu_count = os.process_cpu_count() or os.cpu_count() or 1
    return max(1, min(cpu_count, 1024))


def _string_from_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _path_from_env(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None


def _bool_from_env(name: str) -> bool | None:
    value = _string_from_env(name)
    if value is None:
        return None

    normalized = value.lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _int_from_env(name: str) -> int | None:
    value = _string_from_env(name)
    if value is None:
        return None

    if not value.isdigit():
        return None

    return int(value)


def _json_object_from_path(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        return payload

    return None


def _mapping_at_path(mapping: dict[str, Any] | None, *keys: str) -> dict[str, Any] | None:
    current: object = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    if isinstance(current, dict):
        return current
    return None


def _string_at_path(mapping: dict[str, Any] | None, *keys: str) -> str | None:
    current: object = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    if isinstance(current, str):
        stripped = current.strip()
        return stripped or None
    return None


def _int_from_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _conan_profile_settings(profile_path: Path) -> dict[str, str]:
    if not profile_path.is_file():
        msg = f"Expected the Conan host profile at '{profile_path}'."
        raise FileNotFoundError(msg)

    settings: dict[str, str] = {}
    in_settings = False
    for raw_line in profile_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            in_settings = stripped.casefold() == "[settings]"
            continue

        if not in_settings or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            settings[normalized_key] = normalized_value

    return settings


def _conan_configuration_label(
    profile_path: Path,
    configuration: BuildConfiguration,
) -> str:
    settings = _conan_profile_settings(profile_path)
    os_name = settings.get("os")
    compiler_name = settings.get("compiler")
    if not os_name or not compiler_name:
        msg = (
            f"Conan host profile '{profile_path}' must declare [settings] os and compiler "
            "so the automation can mirror the recipe layout."
        )
        raise ValueError(msg)

    return "-".join((os_name.lower(), compiler_name.lower(), configuration.value.lower()))


def _pull_request_number_from_event(payload: dict[str, Any] | None) -> int | None:
    if payload is None:
        return None

    top_level_number = _int_from_value(payload.get("number"))
    if top_level_number is not None:
        return top_level_number

    pull_request = _mapping_at_path(payload, "pull_request")
    if pull_request is None:
        return None

    return _int_from_value(pull_request.get("number"))


def _event_payload_from_env() -> dict[str, Any] | None:
    return _json_object_from_path(_path_from_env("GITHUB_EVENT_PATH"))


_GITHUB_ACTIONS_EVENT_EXTRACTORS: tuple[
    tuple[str, Callable[[dict[str, Any]], object | None]],
    ...,
] = (
    ("repository", lambda payload: _string_at_path(payload, "repository", "full_name")),
    ("event_action", lambda payload: _string_at_path(payload, "action")),
    ("pull_request_number", _pull_request_number_from_event),
    ("base_ref", lambda payload: _string_at_path(payload, "pull_request", "base", "ref")),
    ("head_ref", lambda payload: _string_at_path(payload, "pull_request", "head", "ref")),
    ("base_sha", lambda payload: _string_at_path(payload, "pull_request", "base", "sha")),
    ("head_sha", lambda payload: _string_at_path(payload, "pull_request", "head", "sha")),
    (
        "sha",
        lambda payload: (
            _string_at_path(payload, "after")
            or _string_at_path(payload, "pull_request", "head", "sha")
        ),
    ),
    ("actor", lambda payload: _string_at_path(payload, "sender", "login")),
)


def _github_actions_event_updates(context: GitHubActionsContext) -> dict[str, object]:
    payload = context.event_payload
    if payload is None:
        return {}

    updates: dict[str, object] = {}
    for field_name, extractor in _GITHUB_ACTIONS_EVENT_EXTRACTORS:
        if getattr(context, field_name) is not None:
            continue

        value = extractor(payload)
        if value is not None:
            updates[field_name] = value

    return updates


def _expected_squid_tag(version: str) -> str:
    return f"SQUID_{version.replace('.', '_')}"


def validate_service_name(value: str, *, parameter_name: str = "ServiceName") -> str:
    resolved_value = value.strip()
    if not resolved_value:
        msg = f"{parameter_name} must contain at least one alphanumeric character."
        raise ValueError(msg)
    if len(resolved_value) > 32:
        msg = (
            f"{parameter_name} '{resolved_value}' must be 32 characters or fewer because "
            "Squid's -n option rejects longer Windows service names."
        )
        raise ValueError(msg)
    if re.fullmatch(r"[A-Za-z0-9]+", resolved_value) is None:
        msg = (
            f"{parameter_name} '{resolved_value}' must be alphanumeric because Squid's "
            "-n option rejects punctuation characters such as '-'."
        )
        raise ValueError(msg)

    return resolved_value


def _first_existing_path(candidates: tuple[Path, ...]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


class GitHubActionsContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = Field(default_factory=lambda: _bool_from_env("GITHUB_ACTIONS") is True)
    workspace: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_WORKSPACE"))
    repository: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_REPOSITORY"))
    server_url: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_SERVER_URL"))
    api_url: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_API_URL"))
    graphql_url: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_GRAPHQL_URL"))
    ref: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_REF"))
    ref_name: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_REF_NAME"))
    ref_type: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_REF_TYPE"))
    ref_protected: bool | None = Field(
        default_factory=lambda: _bool_from_env("GITHUB_REF_PROTECTED")
    )
    sha: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_SHA"))
    actor: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_ACTOR"))
    actor_id: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_ACTOR_ID"))
    triggering_actor: str | None = Field(
        default_factory=lambda: _string_from_env("GITHUB_TRIGGERING_ACTOR")
    )
    base_ref: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_BASE_REF"))
    head_ref: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_HEAD_REF"))
    base_sha: str | None = None
    head_sha: str | None = None
    event_name: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_EVENT_NAME"))
    event_path: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_EVENT_PATH"))
    event_payload: dict[str, Any] | None = Field(default_factory=_event_payload_from_env)
    event_action: str | None = None
    pull_request_number: int | None = None
    job: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_JOB"))
    run_id: int | None = Field(default_factory=lambda: _int_from_env("GITHUB_RUN_ID"))
    run_number: int | None = Field(default_factory=lambda: _int_from_env("GITHUB_RUN_NUMBER"))
    run_attempt: int | None = Field(default_factory=lambda: _int_from_env("GITHUB_RUN_ATTEMPT"))
    workflow: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_WORKFLOW"))
    workflow_ref: str | None = Field(
        default_factory=lambda: _string_from_env("GITHUB_WORKFLOW_REF")
    )
    workflow_sha: str | None = Field(
        default_factory=lambda: _string_from_env("GITHUB_WORKFLOW_SHA")
    )
    action: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_ACTION"))
    action_path: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_ACTION_PATH"))
    action_ref: str | None = Field(default_factory=lambda: _string_from_env("GITHUB_ACTION_REF"))
    action_repository: str | None = Field(
        default_factory=lambda: _string_from_env("GITHUB_ACTION_REPOSITORY")
    )
    output_path: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_OUTPUT"))
    env_path: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_ENV"))
    path_file: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_PATH"))
    step_summary_path: Path | None = Field(
        default_factory=lambda: _path_from_env("GITHUB_STEP_SUMMARY")
    )
    state_path: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_STATE"))

    def model_post_init(self, __context: Any) -> None:
        for field_name, field_value in _github_actions_event_updates(self).items():
            object.__setattr__(self, field_name, field_value)


class RepositoryPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    scripts_root: Path
    build_root: Path
    artifact_root: Path
    config_root: Path
    conan_root: Path
    conan_recipe_root: Path
    conan_home_path: Path
    tray_project_path: Path
    squid_release_metadata_path: Path
    squid_version_config_path: Path
    conan_data_path: Path
    installer_project_path: Path

    @classmethod
    def discover(cls, repository_root: Path | None = None) -> RepositoryPaths:
        root = discover_repository_root(repository_root)
        conan_root = root / "conan"
        conan_recipe_root = conan_root / "recipes" / "squid" / "all"
        config_root = root / "config"

        return cls(
            repository_root=root,
            scripts_root=root / "scripts",
            build_root=root / "build",
            artifact_root=root / "artifacts",
            config_root=config_root,
            conan_root=conan_root,
            conan_recipe_root=conan_recipe_root,
            conan_home_path=root / ".conan2",
            tray_project_path=root / "src" / "tray" / "Squid4Win.Tray" / "Squid4Win.Tray.csproj",
            squid_release_metadata_path=conan_root / "squid-release.json",
            squid_version_config_path=config_root / "squid-version.json",
            conan_data_path=conan_recipe_root / "conandata.yml",
            installer_project_path=root / "packaging" / "wix" / "Squid4Win.Installer.wixproj",
        )


class SquidBuildLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    build_root: Path
    configuration: BuildConfiguration
    configuration_label: str
    conan_configuration_label: str
    profile_name: str
    stage_root: Path
    downloads_root: Path
    sources_root: Path
    work_root: Path
    conan_output_root: Path
    conan_build_root: Path
    conan_install_root: Path
    conan_generators_root: Path
    repo_lockfile_path: Path
    build_lock_path: Path

    @classmethod
    def create(
        cls,
        repository_root: Path,
        build_root: Path,
        configuration: BuildConfiguration,
        *,
        host_profile_path: Path,
    ) -> SquidBuildLayout:
        profile_name = host_profile_path.name
        configuration_label = configuration.value.lower()
        conan_configuration_label = _conan_configuration_label(
            host_profile_path,
            configuration,
        )
        profile_stem = f"{profile_name}-{configuration_label}"

        return cls(
            repository_root=repository_root,
            build_root=build_root,
            configuration=configuration,
            configuration_label=configuration_label,
            conan_configuration_label=conan_configuration_label,
            profile_name=profile_name,
            stage_root=build_root / "install" / configuration_label,
            downloads_root=build_root / "downloads",
            sources_root=build_root / "sources" / profile_stem,
            work_root=build_root / profile_stem,
            conan_output_root=build_root / "conan" / profile_stem,
            conan_build_root=(
                build_root / "conan" / profile_stem / "build" / conan_configuration_label
            ),
            conan_install_root=(
                build_root
                / "conan"
                / profile_stem
                / "build"
                / conan_configuration_label
                / "package"
            ),
            conan_generators_root=(
                build_root / "conan" / profile_stem / "build" / conan_configuration_label / "conan"
            ),
            repo_lockfile_path=repository_root / "conan" / "lockfiles" / f"{profile_stem}.lock",
            build_lock_path=build_root / "locks" / f"{profile_stem}.lock",
        )


class TrayBuildLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    build_root: Path
    configuration: BuildConfiguration
    configuration_label: str
    publish_root: Path
    package_root: Path
    published_tray_executable_path: Path
    packaged_tray_executable_path: Path
    notice_manifest_path: Path

    @classmethod
    def create(
        cls,
        repository_root: Path,
        build_root: Path,
        configuration: BuildConfiguration,
    ) -> TrayBuildLayout:
        configuration_label = configuration.value.lower()
        publish_root = build_root / "tray" / configuration_label / "publish"
        package_root = build_root / "tray" / configuration_label / "package"

        return cls(
            repository_root=repository_root,
            build_root=build_root,
            configuration=configuration,
            configuration_label=configuration_label,
            publish_root=publish_root,
            package_root=package_root,
            published_tray_executable_path=publish_root / _TRAY_EXECUTABLE_NAME,
            packaged_tray_executable_path=package_root / "bin" / _TRAY_EXECUTABLE_NAME,
            notice_manifest_path=package_root / "licenses" / "third-party-package-manifest.json",
        )


class BundlePackageState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    build_root: Path
    configuration: BuildConfiguration
    configuration_label: str
    squid_stage_root: Path
    artifact_root: Path
    installer_project_path: Path
    installer_payload_root: Path
    installer_core_payload_root: Path
    installer_tray_payload_root: Path
    portable_zip_path: Path
    msi_path: Path
    tray_package_root: Path
    tray_package_executable_path: Path
    tray_notice_manifest_path: Path
    stage_root_exists: bool
    staged_squid_executable_path: Path | None
    staged_tray_executable_path: Path
    staged_notices_path: Path
    staged_service_script_path: Path
    staged_config_template_path: Path
    staged_html_docs_index_path: Path
    staged_raw_man_root_path: Path
    tray_package_available: bool
    tray_notice_manifest_available: bool
    staged_tray_available: bool
    staged_notices_available: bool
    packaging_support_available: bool

    @classmethod
    def inspect(
        cls,
        repository_root: Path,
        build_root: Path,
        configuration: BuildConfiguration,
        *,
        squid_stage_root: Path,
        artifact_root: Path,
        installer_project_path: Path,
    ) -> BundlePackageState:
        configuration_label = configuration.value.lower()
        tray_layout = TrayBuildLayout.create(repository_root, build_root, configuration)
        staged_squid_executable_path = _first_existing_path(
            (
                squid_stage_root / "sbin" / "squid.exe",
                squid_stage_root / "bin" / "squid.exe",
            )
        )
        staged_tray_executable_path = squid_stage_root / _TRAY_EXECUTABLE_NAME
        staged_notices_path = squid_stage_root / "THIRD-PARTY-NOTICES.txt"
        staged_service_script_path = squid_stage_root / "installer" / "svc.ps1"
        staged_config_template_path = squid_stage_root / "etc" / "squid.conf.template"
        staged_html_docs_index_path = squid_stage_root / "docs" / "html" / "index.html"
        staged_raw_man_root_path = squid_stage_root / "share" / "man"

        return cls(
            repository_root=repository_root,
            build_root=build_root,
            configuration=configuration,
            configuration_label=configuration_label,
            squid_stage_root=squid_stage_root,
            artifact_root=artifact_root,
            installer_project_path=installer_project_path,
            installer_payload_root=artifact_root / "install-root",
            installer_core_payload_root=artifact_root / "install-root-core",
            installer_tray_payload_root=artifact_root / "install-root-tray",
            portable_zip_path=artifact_root / "squid4win-portable.zip",
            msi_path=artifact_root / "squid4win.msi",
            tray_package_root=tray_layout.package_root,
            tray_package_executable_path=tray_layout.packaged_tray_executable_path,
            tray_notice_manifest_path=tray_layout.notice_manifest_path,
            stage_root_exists=squid_stage_root.is_dir(),
            staged_squid_executable_path=staged_squid_executable_path,
            staged_tray_executable_path=staged_tray_executable_path,
            staged_notices_path=staged_notices_path,
            staged_service_script_path=staged_service_script_path,
            staged_config_template_path=staged_config_template_path,
            staged_html_docs_index_path=staged_html_docs_index_path,
            staged_raw_man_root_path=staged_raw_man_root_path,
            tray_package_available=tray_layout.packaged_tray_executable_path.is_file(),
            tray_notice_manifest_available=tray_layout.notice_manifest_path.is_file(),
            staged_tray_available=staged_tray_executable_path.is_file(),
            staged_notices_available=staged_notices_path.is_file(),
            packaging_support_available=(
                staged_service_script_path.is_file()
                and staged_config_template_path.is_file()
                and staged_html_docs_index_path.is_file()
                and not staged_raw_man_root_path.exists()
            ),
        )


class ProcessInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    command: tuple[str, ...]
    cwd: Path | None = None
    environment: dict[str, str] = Field(default_factory=dict)

    def render(self) -> str:
        return subprocess.list2cmdline(list(self.command))


class AutomationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    summary: str
    repository_root: Path
    commands: tuple[ProcessInvocation, ...]


class SquidBuildOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    metadata_path: Path | None = None
    host_profile_path: Path | None = None
    build_profile: str = "default"
    lockfile_path: Path | None = None
    additional_configure_args: tuple[str, ...] = ()
    make_jobs: Annotated[int, Field(ge=1, le=1024)] = Field(default_factory=default_make_jobs)
    bootstrap_only: bool = False
    refresh_lockfile: bool = False
    clean: bool = False
    with_tray: bool = False
    with_runtime_dlls: bool = False
    with_packaging_support: bool = False
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )

    @model_validator(mode="after")
    def validate_option_dependencies(self) -> SquidBuildOptions:
        if self.with_runtime_dlls and not self.with_packaging_support:
            msg = (
                "--with-runtime-dlls requires --with-packaging-support so the "
                "bundled notices and source manifest stay aligned."
            )
            raise ValueError(msg)
        return self


class TrayBuildOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    project_path: Path | None = None
    publish_root: Path | None = None
    package_root: Path | None = None


class ConanRecipeValidationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    host_profile_path: Path | None = None
    build_profile: str = "default"
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )
    openssl_linkage: ConanDependencyLinkage = ConanDependencyLinkage.DEFAULT

    @model_validator(mode="after")
    def validate_linkage_dependencies(self) -> ConanRecipeValidationOptions:
        if (
            self.openssl_linkage is not ConanDependencyLinkage.DEFAULT
            and self.dependency_sources.openssl_source is not DependencySource.CONAN
        ):
            msg = "--openssl-linkage requires --openssl-source conan."
            raise ValueError(msg)
        return self


class ConanRecipeArtifactStageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    artifact_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    host_profile_path: Path | None = None
    compiler_label: str | None = None
    library_configuration_label: Annotated[str, Field(min_length=1)]
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )
    openssl_linkage: ConanDependencyLinkage = ConanDependencyLinkage.DEFAULT

    @model_validator(mode="after")
    def validate_linkage_dependencies(self) -> ConanRecipeArtifactStageOptions:
        if (
            self.openssl_linkage is not ConanDependencyLinkage.DEFAULT
            and self.dependency_sources.openssl_source is not DependencySource.CONAN
        ):
            msg = "--openssl-linkage requires --openssl-source conan."
            raise ValueError(msg)
        return self


class ConanLockfileUpdateOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    host_profile_path: Path | None = None
    build_profile: str = "default"
    lockfile_path: Path | None = None
    with_tray: bool = False
    with_runtime_dlls: bool = False
    with_packaging_support: bool = False
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )

    @model_validator(mode="after")
    def validate_option_dependencies(self) -> ConanLockfileUpdateOptions:
        if self.with_runtime_dlls and not self.with_packaging_support:
            msg = (
                "--with-runtime-dlls requires --with-packaging-support so the "
                "bundled notices and source manifest stay aligned."
            )
            raise ValueError(msg)
        return self


class BundlePackageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    squid_stage_root: Path | None = None
    artifact_root: Path | None = None
    installer_project_path: Path | None = None
    create_portable_zip: bool = False
    sign_payload_files: bool = False
    require_tray: bool = False
    require_notices: bool = False
    build_installer: bool = True
    product_version: str | None = None
    service_name: str = "Squid4Win"
    sign_msi: bool = False
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        return validate_service_name(value, parameter_name="ServiceName")

    @model_validator(mode="after")
    def validate_bundle_dependencies(self) -> BundlePackageOptions:
        if self.sign_msi and not self.build_installer:
            msg = "--sign-msi requires installer building to remain enabled."
            raise ValueError(msg)

        if self.product_version is not None and not self.build_installer:
            msg = "--product-version is only valid when installer building is enabled."
            raise ValueError(msg)

        return self


class SmokeTestOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    squid_stage_root: Path | None = None
    metadata_path: Path | None = None
    binary_path: Path | None = None
    require_notices: bool = False


class SmokeTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binary_path: Path
    install_root: Path
    version: str
    executable_directories: tuple[Path, ...]
    runtime_dlls: tuple[str, ...]
    runtime_notice_packages: tuple[dict[str, Any], ...]
    tray_notice_packages: tuple[dict[str, Any], ...]
    notices_path: Path | None = None
    security_file_certgen_path: Path | None = None


class ServiceRunnerValidationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    configuration: BuildConfiguration = BuildConfiguration.RELEASE
    build_root: Path | None = None
    artifact_root: Path | None = None
    service_name: str | None = None
    service_name_prefix: str = "Squid4WinRunner"
    install_root: Path | None = None
    service_timeout_seconds: Annotated[int, Field(ge=1, le=600)] = 60
    allow_non_runner_execution: bool = False
    require_tray: bool = True
    require_notices: bool = True
    dependency_sources: NativeDependencySourceOptions = Field(
        default_factory=NativeDependencySourceOptions
    )

    @field_validator("service_name")
    @classmethod
    def validate_explicit_service_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_service_name(value, parameter_name="ServiceName")


class ServiceRunnerValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_root: Path
    install_root: Path
    msi_path: Path | None = None
    service_name: str
    service_command_line: str | None = None
    validated_http_port: int | None = None
    cleanup_actions: tuple[str, ...]
    cleanup_issues: tuple[str, ...]


class ProxyRuntimeValidationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    artifact_root: Path | None = None
    proxy_url: str = "http://127.0.0.1:3128"
    binary_path: Path | None = None
    install_root: Path | None = None
    request_timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 20
    burst_requests: Annotated[int, Field(ge=8, le=4000)] = 128
    burst_concurrency: Annotated[int, Field(ge=1, le=256)] = 16
    include_external: bool = True
    log_tail_lines: Annotated[int, Field(ge=20, le=2000)] = 200

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            msg = "--proxy-url must use an http or https scheme."
            raise ValueError(msg)
        if not parsed.hostname or parsed.port is None:
            msg = "--proxy-url must include an explicit host and port."
            raise ValueError(msg)
        return value


class ProxyRuntimeValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_root: Path
    summary_path: Path
    json_path: Path
    proxy_url: str
    target_mode: str
    scenario_count: int
    failed_scenarios: int
    request_count: int
    failed_requests: int


class PackageManagerExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    tag: Annotated[str | None, Field(min_length=1)] = None
    repository: str = _DEFAULT_REPOSITORY
    msi_path: Path | None = None
    portable_zip_path: Path | None = None
    output_root: Path | None = None
    package_identifier: Annotated[str, Field(min_length=1)] = "JanGuenter.Squid4Win"
    package_name: Annotated[str, Field(min_length=1)] = "Squid4Win"
    publisher: Annotated[str, Field(min_length=1)] = "Jan Guenter"
    publisher_url: Annotated[str, Field(min_length=1)] = "https://github.com/jan-guenter"
    package_url: Annotated[str | None, Field(min_length=1)] = None
    msi_url: Annotated[str | None, Field(min_length=1)] = None
    portable_zip_url: Annotated[str | None, Field(min_length=1)] = None

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(_REPOSITORY_PATTERN, value):
            msg = _REPOSITORY_FORMAT_MESSAGE
            raise ValueError(msg)
        return value


class PackageManagerExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output_root: Path
    winget_root: Path
    chocolatey_root: Path
    scoop_manifest_path: Path
    msi_sha256: str
    portable_zip_sha256: str
    msi_url: str
    portable_zip_url: str


class PublishWingetOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    tag: Annotated[str | None, Field(min_length=1)] = None
    repository: str = _DEFAULT_REPOSITORY
    manifest_root: Path | None = None
    package_identifier: Annotated[str, Field(min_length=1)] = "JanGuenter.Squid4Win"
    target_repository: str = "microsoft/winget-pkgs"
    base_branch: Annotated[str, Field(min_length=1)] = "master"
    working_root: Path | None = None

    @field_validator("repository", "target_repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(_REPOSITORY_PATTERN, value):
            msg = _REPOSITORY_FORMAT_MESSAGE
            raise ValueError(msg)
        return value


class PublishScoopOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    tag: Annotated[str | None, Field(min_length=1)] = None
    repository: str = _DEFAULT_REPOSITORY
    manifest_root: Path | None = None
    target_repository: str
    base_branch: Annotated[str, Field(min_length=1)] = "master"
    package_file_name: Annotated[str, Field(min_length=1)] = "squid4win.json"
    working_root: Path | None = None

    @field_validator("repository", "target_repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(_REPOSITORY_PATTERN, value):
            msg = _REPOSITORY_FORMAT_MESSAGE
            raise ValueError(msg)
        return value


class PublishChocolateyOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    package_root: Path | None = None
    package_id: Annotated[str, Field(min_length=1)] = "squid4win"
    push_source: Annotated[str, Field(min_length=1)] = "https://push.chocolatey.org/"
    query_source: Annotated[str, Field(min_length=1)] = "https://community.chocolatey.org/api/v2/"
    output_root: Path | None = None


class GitHubPublicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    changed: bool
    pull_request_url: str | None = None
    head_repository: str
    base_repository: str
    branch_name: str
    destination_path: str


class ChocolateyPublicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    already_published: bool
    package_path: Path | None = None
    push_source: str
    query_source: str


class UpstreamVersionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    metadata_path: Path | None = None
    config_path: Path | None = None
    conan_data_path: Path | None = None
    repository: str = "squid-cache/squid"
    major_version: Annotated[int | None, Field(ge=1)] = None
    include_prerelease: bool = False
    version: str | None = None
    tag: str | None = None
    published_at: str | None = None
    source_archive: AnyHttpUrl | None = None
    source_signature: AnyHttpUrl | None = None
    source_archive_sha256: str | None = None

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(_REPOSITORY_PATTERN, value):
            msg = _REPOSITORY_FORMAT_MESSAGE
            raise ValueError(msg)
        return value

    @field_validator("source_archive_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return value

        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            msg = "Source archive digests must be 64-character SHA256 values."
            raise ValueError(msg)
        return value.lower()

    @model_validator(mode="after")
    def validate_manual_release_values(self) -> UpstreamVersionOptions:
        manual_values = (
            self.version,
            self.tag,
            self.published_at,
            self.source_archive,
            self.source_signature,
            self.source_archive_sha256,
        )
        if not any(value is not None for value in manual_values):
            return self

        missing = [
            field_name
            for field_name in ("version", "tag", "source_archive", "source_archive_sha256")
            if getattr(self, field_name) is None
        ]
        if missing:
            joined = ", ".join(missing)
            msg = (
                "Manual upstream version updates require explicit values for "
                f"{joined}; omit the overrides entirely to let the GitHub client resolve them."
            )
            raise ValueError(msg)

        if self.version is not None and self.tag is not None:
            expected_tag = _expected_squid_tag(self.version)
            if self.tag != expected_tag:
                msg = (
                    f"Manual upstream tags must match version {self.version} using {expected_tag}."
                )
                raise ValueError(msg)

        if self.major_version is not None and self.version is not None:
            version_match = re.match(r"(?P<major>\d+)", self.version)
            if (
                version_match is not None
                and int(version_match.group("major")) != self.major_version
            ):
                msg = (
                    "Manual upstream version updates must keep --major-version aligned with "
                    "the explicit --version value."
                )
                raise ValueError(msg)
        return self
