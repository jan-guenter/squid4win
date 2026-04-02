from __future__ import annotations

import json
import os
import re
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from squid4win.paths import discover_repository_root

_DEFAULT_REPOSITORY = "jan-guenter/squid4win"
_REPOSITORY_PATTERN = r"[^/]+/[^/]+"
_REPOSITORY_FORMAT_MESSAGE = "Repository values must follow the owner/name format."
_TRAY_EXECUTABLE_NAME = "Squid4Win.Tray.exe"


class BuildConfiguration(StrEnum):
    DEBUG = "Debug"
    RELEASE = "Release"


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
        if self.event_payload is None:
            return

        updates: dict[str, object] = {}
        if self.repository is None:
            repository = _string_at_path(self.event_payload, "repository", "full_name")
            if repository is not None:
                updates["repository"] = repository

        if self.event_action is None:
            event_action = _string_at_path(self.event_payload, "action")
            if event_action is not None:
                updates["event_action"] = event_action

        if self.pull_request_number is None:
            pull_request_number = _pull_request_number_from_event(self.event_payload)
            if pull_request_number is not None:
                updates["pull_request_number"] = pull_request_number

        if self.base_ref is None:
            base_ref = _string_at_path(self.event_payload, "pull_request", "base", "ref")
            if base_ref is not None:
                updates["base_ref"] = base_ref

        if self.head_ref is None:
            head_ref = _string_at_path(self.event_payload, "pull_request", "head", "ref")
            if head_ref is not None:
                updates["head_ref"] = head_ref

        if self.base_sha is None:
            base_sha = _string_at_path(self.event_payload, "pull_request", "base", "sha")
            if base_sha is not None:
                updates["base_sha"] = base_sha

        if self.head_sha is None:
            head_sha = _string_at_path(self.event_payload, "pull_request", "head", "sha")
            if head_sha is not None:
                updates["head_sha"] = head_sha

        if self.sha is None:
            sha = _string_at_path(self.event_payload, "after") or _string_at_path(
                self.event_payload,
                "pull_request",
                "head",
                "sha",
            )
            if sha is not None:
                updates["sha"] = sha

        if self.actor is None:
            actor = _string_at_path(self.event_payload, "sender", "login")
            if actor is not None:
                updates["actor"] = actor

        if updates:
            for field_name, field_value in updates.items():
                object.__setattr__(self, field_name, field_value)


class RepositoryPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    scripts_root: Path
    build_root: Path
    artifact_root: Path
    config_root: Path
    conan_root: Path
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
        config_root = root / "config"

        return cls(
            repository_root=root,
            scripts_root=root / "scripts",
            build_root=root / "build",
            artifact_root=root / "artifacts",
            config_root=config_root,
            conan_root=conan_root,
            conan_home_path=root / ".conan2",
            tray_project_path=root / "src" / "tray" / "Squid4Win.Tray" / "Squid4Win.Tray.csproj",
            squid_release_metadata_path=conan_root / "squid-release.json",
            squid_version_config_path=config_root / "squid-version.json",
            conan_data_path=root / "conandata.yml",
            installer_project_path=root / "packaging" / "wix" / "Squid4Win.Installer.wixproj",
        )


class SquidBuildLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path
    build_root: Path
    configuration: BuildConfiguration
    configuration_label: str
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
        profile_name: str = "msys2-mingw-x64",
    ) -> SquidBuildLayout:
        configuration_label = configuration.value.lower()
        profile_stem = f"{profile_name}-{configuration_label}"

        return cls(
            repository_root=repository_root,
            build_root=build_root,
            configuration=configuration,
            configuration_label=configuration_label,
            profile_name=profile_name,
            stage_root=build_root / "install" / configuration_label,
            downloads_root=build_root / "downloads",
            sources_root=build_root / "sources" / profile_stem,
            work_root=build_root / profile_stem,
            conan_output_root=build_root / "conan" / profile_stem,
            conan_build_root=build_root / "conan" / profile_stem / "build" / configuration_label,
            conan_install_root=(
                build_root / "conan" / profile_stem / "build" / configuration_label / "package"
            ),
            conan_generators_root=(
                build_root / "conan" / profile_stem / "build" / configuration_label / "conan"
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

        return cls(
            repository_root=repository_root,
            build_root=build_root,
            configuration=configuration,
            configuration_label=configuration_label,
            squid_stage_root=squid_stage_root,
            artifact_root=artifact_root,
            installer_project_path=installer_project_path,
            installer_payload_root=artifact_root / "install-root",
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
            tray_package_available=tray_layout.packaged_tray_executable_path.is_file(),
            tray_notice_manifest_available=tray_layout.notice_manifest_path.is_file(),
            staged_tray_available=staged_tray_executable_path.is_file(),
            staged_notices_available=staged_notices_path.is_file(),
            packaging_support_available=(
                staged_service_script_path.is_file() and staged_config_template_path.is_file()
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
    make_jobs: Annotated[int, Field(ge=1, le=1024)] = 1
    bootstrap_only: bool = False
    refresh_lockfile: bool = False
    clean: bool = False
    with_tray: bool = False
    with_runtime_dlls: bool = False
    with_packaging_support: bool = False

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
    cleanup_actions: tuple[str, ...]
    cleanup_issues: tuple[str, ...]


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
