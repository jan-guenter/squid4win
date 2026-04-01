from __future__ import annotations

import os
import re
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from squid4win.paths import discover_repository_root


class BuildConfiguration(StrEnum):
    DEBUG = "Debug"
    RELEASE = "Release"


def _path_from_env(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None


def _expected_squid_tag(version: str) -> str:
    return f"SQUID_{version.replace('.', '_')}"


def _first_existing_path(candidates: tuple[Path, ...]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


class GitHubActionsContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = Field(default_factory=lambda: os.getenv("GITHUB_ACTIONS", "").lower() == "true")
    workspace: Path | None = Field(default_factory=lambda: _path_from_env("GITHUB_WORKSPACE"))
    repository: str | None = Field(default_factory=lambda: os.getenv("GITHUB_REPOSITORY"))
    ref: str | None = Field(default_factory=lambda: os.getenv("GITHUB_REF"))
    sha: str | None = Field(default_factory=lambda: os.getenv("GITHUB_SHA"))
    actor: str | None = Field(default_factory=lambda: os.getenv("GITHUB_ACTOR"))


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
            conan_generators_root=(
                build_root / "conan" / profile_stem / f"build-{configuration_label}" / "conan"
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
            published_tray_executable_path=publish_root / "Squid4Win.Tray.exe",
            packaged_tray_executable_path=package_root / "bin" / "Squid4Win.Tray.exe",
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
        staged_tray_executable_path = squid_stage_root / "Squid4Win.Tray.exe"
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
        if not re.fullmatch(r"[A-Za-z0-9]{1,32}", value):
            msg = "Service names must be alphanumeric and at most 32 characters long."
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_bundle_dependencies(self) -> BundlePackageOptions:
        if self.sign_msi and not self.build_installer:
            msg = "--sign-msi requires installer building to remain enabled."
            raise ValueError(msg)

        if self.product_version is not None and not self.build_installer:
            msg = "--product-version is only valid when installer building is enabled."
            raise ValueError(msg)

        return self


class PackageManagerExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    tag: Annotated[str | None, Field(min_length=1)] = None
    repository: str = "jan-guenter/squid4win"
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
        if not re.fullmatch(r"[^/]+/[^/]+", value):
            msg = "Repository values must follow the owner/name format."
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
    repository: str = "jan-guenter/squid4win"
    manifest_root: Path | None = None
    package_identifier: Annotated[str, Field(min_length=1)] = "JanGuenter.Squid4Win"
    target_repository: str = "microsoft/winget-pkgs"
    base_branch: Annotated[str, Field(min_length=1)] = "master"
    working_root: Path | None = None

    @field_validator("repository", "target_repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(r"[^/]+/[^/]+", value):
            msg = "Repository values must follow the owner/name format."
            raise ValueError(msg)
        return value


class PublishScoopOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_root: Path | None = None
    version: Annotated[str, Field(min_length=1)]
    tag: Annotated[str | None, Field(min_length=1)] = None
    repository: str = "jan-guenter/squid4win"
    manifest_root: Path | None = None
    target_repository: str
    base_branch: Annotated[str, Field(min_length=1)] = "master"
    package_file_name: Annotated[str, Field(min_length=1)] = "squid4win.json"
    working_root: Path | None = None

    @field_validator("repository", "target_repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not re.fullmatch(r"[^/]+/[^/]+", value):
            msg = "Repository values must follow the owner/name format."
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
        if not re.fullmatch(r"[^/]+/[^/]+", value):
            msg = "Repository values must follow the owner/name format."
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
