from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import httpx
from pydantic import ValidationError

from squid4win.commands import (
    run_bundle_package,
    run_conan_lockfile_update,
    run_conan_recipe_validation,
    run_service_runner_validation,
    run_smoke_test,
    run_squid_build,
    run_tray_build,
)
from squid4win.logging_utils import configure_logging, get_logger
from squid4win.models import (
    BundlePackageOptions,
    ConanDependencyLinkage,
    ConanLockfileUpdateOptions,
    ConanRecipeValidationOptions,
    DependencySource,
    NativeDependencySourceOptions,
    PackageManagerExportOptions,
    PublishChocolateyOptions,
    PublishScoopOptions,
    PublishWingetOptions,
    ServiceRunnerValidationOptions,
    SmokeTestOptions,
    SquidBuildOptions,
    TrayBuildOptions,
    UpstreamVersionOptions,
)
from squid4win.package_managers import (
    run_package_manager_export,
    run_publish_chocolatey,
    run_publish_scoop,
    run_publish_winget,
)
from squid4win.runner import PlanExecutionError, PlanRunner
from squid4win.upstream import GitHubReleaseClient
from squid4win.utils.actions import context as github_actions_context
from squid4win.version_helper import TargetUpstreamRelease, UpstreamVersionManager

_DEFAULT_REPOSITORY = "jan-guenter/squid4win"
_DEPENDENCY_SOURCE_CHOICES = tuple(source.value for source in DependencySource)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="squid4win-automation",
        description="Python automation foundation for squid4win.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Set the logging verbosity.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    squid_build = subparsers.add_parser(
        "squid-build",
        help=(
            "Plan or run the CCI-style Squid recipe build from "
            "conan\\recipes\\squid\\all with native Python orchestration."
        ),
    )
    _add_common_command_arguments(squid_build)
    squid_build.add_argument("--configuration", choices=("Debug", "Release"), default="Release")
    squid_build.add_argument("--build-root", type=Path)
    squid_build.add_argument("--metadata-path", type=Path)
    squid_build.add_argument("--host-profile-path", type=Path)
    squid_build.add_argument("--build-profile", default="default")
    squid_build.add_argument("--lockfile-path", type=Path)
    squid_build.add_argument("--additional-configure-arg", action="append", default=[])
    squid_build.add_argument("--make-jobs", type=int, default=1)
    squid_build.add_argument("--bootstrap-only", action="store_true")
    squid_build.add_argument("--refresh-lockfile", action="store_true")
    squid_build.add_argument("--clean", action="store_true")
    squid_build.add_argument("--with-tray", action="store_true")
    squid_build.add_argument("--with-runtime-dlls", action="store_true")
    squid_build.add_argument("--with-packaging-support", action="store_true")
    _add_dependency_source_arguments(squid_build)
    squid_build.set_defaults(handler=_handle_squid_build)

    tray_build = subparsers.add_parser(
        "tray-build",
        help="Plan or run the direct .NET tray build with native Python orchestration.",
    )
    _add_common_command_arguments(tray_build)
    tray_build.add_argument("--configuration", choices=("Debug", "Release"), default="Release")
    tray_build.add_argument(
        "--publish-root",
        type=Path,
        help="Override the dotnet publish output root.",
    )
    tray_build.add_argument(
        "--package-root",
        "--output-root",
        dest="package_root",
        type=Path,
        help="Override the materialized tray package root copied from the publish output.",
    )
    tray_build.set_defaults(handler=_handle_tray_build)

    conan_lockfile_update = subparsers.add_parser(
        "conan-lockfile-update",
        help="Plan or refresh the selected Conan lockfile with native Python orchestration.",
    )
    _add_common_command_arguments(conan_lockfile_update)
    conan_lockfile_update.add_argument(
        "--configuration",
        choices=("Debug", "Release"),
        default="Release",
    )
    conan_lockfile_update.add_argument("--build-root", type=Path)
    conan_lockfile_update.add_argument("--host-profile-path", type=Path)
    conan_lockfile_update.add_argument("--build-profile", default="default")
    conan_lockfile_update.add_argument("--lockfile-path", type=Path)
    conan_lockfile_update.add_argument("--with-tray", action="store_true")
    conan_lockfile_update.add_argument("--with-runtime-dlls", action="store_true")
    conan_lockfile_update.add_argument("--with-packaging-support", action="store_true")
    _add_dependency_source_arguments(conan_lockfile_update)
    conan_lockfile_update.set_defaults(handler=_handle_conan_lockfile_update)

    conan_recipe_validate = subparsers.add_parser(
        "conan-recipe-validate",
        help="Plan or run conan create validation for the standalone Squid recipe.",
    )
    _add_common_command_arguments(conan_recipe_validate)
    conan_recipe_validate.add_argument(
        "--configuration",
        choices=("Debug", "Release"),
        default="Release",
    )
    conan_recipe_validate.add_argument("--host-profile-path", type=Path)
    conan_recipe_validate.add_argument("--build-profile", default="default")
    conan_recipe_validate.add_argument(
        "--openssl-linkage",
        choices=tuple(linkage.value for linkage in ConanDependencyLinkage),
        default=ConanDependencyLinkage.DEFAULT.value,
        help=(
            "Override the Conan OpenSSL package linkage. Use 'shared' for the mixed "
            "Conan dependency profile or 'static' for the fully static Conan profile."
        ),
    )
    _add_dependency_source_arguments(conan_recipe_validate)
    conan_recipe_validate.set_defaults(handler=_handle_conan_recipe_validate)

    bundle_package = subparsers.add_parser(
        "bundle-package",
        help=(
            "Plan or run payload staging, installer packaging, and any missing prerequisite builds."
        ),
    )
    _add_common_command_arguments(bundle_package)
    bundle_package.add_argument("--configuration", choices=("Debug", "Release"), default="Release")
    bundle_package.add_argument("--build-root", type=Path)
    bundle_package.add_argument("--squid-stage-root", type=Path)
    bundle_package.add_argument("--artifact-root", type=Path)
    bundle_package.add_argument("--installer-project-path", type=Path)
    bundle_package.add_argument("--create-portable-zip", action="store_true")
    bundle_package.add_argument("--sign-payload-files", action="store_true")
    bundle_package.add_argument("--require-tray", action="store_true")
    bundle_package.add_argument("--require-notices", action="store_true")
    bundle_package.add_argument("--skip-installer", action="store_true")
    bundle_package.add_argument("--product-version")
    bundle_package.add_argument("--service-name", default="Squid4Win")
    bundle_package.add_argument("--sign-msi", action="store_true")
    _add_dependency_source_arguments(bundle_package)
    bundle_package.set_defaults(handler=_handle_bundle_package)

    smoke_test = subparsers.add_parser(
        "smoke-test",
        help="Plan or validate the staged Squid bundle, runtime DLLs, and notices.",
    )
    _add_common_command_arguments(smoke_test)
    smoke_test.add_argument("--configuration", choices=("Debug", "Release"), default="Release")
    smoke_test.add_argument("--build-root", type=Path)
    smoke_test.add_argument("--squid-stage-root", type=Path)
    smoke_test.add_argument("--metadata-path", type=Path)
    smoke_test.add_argument("--binary-path", type=Path)
    smoke_test.add_argument("--require-notices", action="store_true")
    smoke_test.set_defaults(handler=_handle_smoke_test)

    service_runner_validation = subparsers.add_parser(
        "service-runner-validation",
        help="Plan or validate the MSI-installed Windows service lifecycle.",
    )
    _add_common_command_arguments(service_runner_validation)
    service_runner_validation.add_argument(
        "--configuration",
        choices=("Debug", "Release"),
        default="Release",
    )
    service_runner_validation.add_argument("--build-root", type=Path)
    service_runner_validation.add_argument("--artifact-root", type=Path)
    service_runner_validation.add_argument("--service-name")
    service_runner_validation.add_argument(
        "--service-name-prefix",
        default="Squid4WinRunner",
    )
    service_runner_validation.add_argument("--install-root", type=Path)
    service_runner_validation.add_argument(
        "--service-timeout-seconds",
        type=int,
        default=60,
    )
    service_runner_validation.add_argument(
        "--allow-non-runner-execution",
        action="store_true",
    )
    _add_dependency_source_arguments(service_runner_validation)
    service_runner_validation.set_defaults(handler=_handle_service_runner_validation)

    package_manager_export = subparsers.add_parser(
        "package-manager-export",
        help="Plan or generate winget, Chocolatey, and Scoop metadata from released binaries.",
    )
    _add_common_command_arguments(package_manager_export)
    package_manager_export.add_argument("--version", required=True)
    package_manager_export.add_argument("--tag")
    package_manager_export.add_argument("--repository", default=_DEFAULT_REPOSITORY)
    package_manager_export.add_argument("--msi-path", type=Path)
    package_manager_export.add_argument("--portable-zip-path", type=Path)
    package_manager_export.add_argument("--output-root", type=Path)
    package_manager_export.add_argument("--package-identifier", default="JanGuenter.Squid4Win")
    package_manager_export.add_argument("--package-name", default="Squid4Win")
    package_manager_export.add_argument("--publisher", default="Jan Guenter")
    package_manager_export.add_argument("--publisher-url", default="https://github.com/jan-guenter")
    package_manager_export.add_argument("--package-url")
    package_manager_export.add_argument("--msi-url")
    package_manager_export.add_argument("--portable-zip-url")
    package_manager_export.set_defaults(handler=_handle_package_manager_export)

    publish_winget = subparsers.add_parser(
        "publish-winget",
        help="Plan or publish the generated winget manifests through a GitHub pull request.",
    )
    _add_common_command_arguments(publish_winget)
    publish_winget.add_argument("--version", required=True)
    publish_winget.add_argument("--tag")
    publish_winget.add_argument("--repository", default=_DEFAULT_REPOSITORY)
    publish_winget.add_argument("--manifest-root", type=Path)
    publish_winget.add_argument("--package-identifier", default="JanGuenter.Squid4Win")
    publish_winget.add_argument("--target-repository", default="microsoft/winget-pkgs")
    publish_winget.add_argument("--base-branch", default="master")
    publish_winget.add_argument("--working-root", type=Path)
    publish_winget.set_defaults(handler=_handle_publish_winget)

    publish_chocolatey = subparsers.add_parser(
        "publish-chocolatey",
        help="Plan or publish the generated Chocolatey package metadata and nupkg.",
    )
    _add_common_command_arguments(publish_chocolatey)
    publish_chocolatey.add_argument("--version", required=True)
    publish_chocolatey.add_argument("--package-root", type=Path)
    publish_chocolatey.add_argument("--package-id", default="squid4win")
    publish_chocolatey.add_argument("--push-source", default="https://push.chocolatey.org/")
    publish_chocolatey.add_argument("--query-source", default="https://community.chocolatey.org/api/v2/")
    publish_chocolatey.add_argument("--output-root", type=Path)
    publish_chocolatey.set_defaults(handler=_handle_publish_chocolatey)

    publish_scoop = subparsers.add_parser(
        "publish-scoop",
        help="Plan or publish the generated Scoop manifest through a GitHub pull request.",
    )
    _add_common_command_arguments(publish_scoop)
    publish_scoop.add_argument("--version", required=True)
    publish_scoop.add_argument("--tag")
    publish_scoop.add_argument("--repository", default=_DEFAULT_REPOSITORY)
    publish_scoop.add_argument("--manifest-root", type=Path)
    publish_scoop.add_argument("--target-repository", required=True)
    publish_scoop.add_argument("--base-branch", default="master")
    publish_scoop.add_argument("--package-file-name", default="squid4win.json")
    publish_scoop.add_argument("--working-root", type=Path)
    publish_scoop.set_defaults(handler=_handle_publish_scoop)

    upstream_version = subparsers.add_parser(
        "upstream-version",
        help="Preview or apply upstream Squid version metadata synchronization.",
    )
    _add_common_command_arguments(upstream_version)
    upstream_version.add_argument("--metadata-path", type=Path)
    upstream_version.add_argument("--config-path", type=Path)
    upstream_version.add_argument("--conan-data-path", type=Path)
    upstream_version.add_argument("--repository", default="squid-cache/squid")
    upstream_version.add_argument("--major-version", type=int)
    upstream_version.add_argument("--include-prerelease", action="store_true")
    upstream_version.add_argument("--version")
    upstream_version.add_argument("--tag")
    upstream_version.add_argument("--published-at")
    upstream_version.add_argument("--source-archive")
    upstream_version.add_argument("--source-signature")
    upstream_version.add_argument("--source-archive-sha256")
    upstream_version.set_defaults(handler=_handle_upstream_version)

    return parser


def _add_common_command_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the planned changes instead of logging a dry run.",
    )


def _add_dependency_source_arguments(parser: argparse.ArgumentParser) -> None:
    for dependency_name in ("openssl", "libxml2", "pcre2", "zlib"):
        parser.add_argument(
            f"--{dependency_name}-source",
            choices=_DEPENDENCY_SOURCE_CHOICES,
            default=DependencySource.SYSTEM.value,
            help=(
                f"Select whether {dependency_name} comes from Conan requirements "
                "or system packages (MSYS2 on Windows)."
            ),
        )


def _dependency_sources_from_args(args: argparse.Namespace) -> NativeDependencySourceOptions:
    return NativeDependencySourceOptions(
        openssl_source=DependencySource(args.openssl_source),
        libxml2_source=DependencySource(args.libxml2_source),
        pcre2_source=DependencySource(args.pcre2_source),
        zlib_source=DependencySource(args.zlib_source),
    )


def _handle_squid_build(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = SquidBuildOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        build_root=args.build_root,
        metadata_path=args.metadata_path,
        host_profile_path=args.host_profile_path,
        build_profile=args.build_profile,
        lockfile_path=args.lockfile_path,
        additional_configure_args=tuple(args.additional_configure_arg),
        make_jobs=args.make_jobs,
        bootstrap_only=args.bootstrap_only,
        refresh_lockfile=args.refresh_lockfile,
        clean=args.clean,
        with_tray=args.with_tray,
        with_runtime_dlls=args.with_runtime_dlls,
        with_packaging_support=args.with_packaging_support,
        dependency_sources=_dependency_sources_from_args(args),
    )
    return run_squid_build(options, runner, execute=args.execute)


def _handle_tray_build(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = TrayBuildOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        publish_root=args.publish_root,
        package_root=args.package_root,
    )
    return run_tray_build(options, runner, execute=args.execute)


def _handle_conan_lockfile_update(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = ConanLockfileUpdateOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        build_root=args.build_root,
        host_profile_path=args.host_profile_path,
        build_profile=args.build_profile,
        lockfile_path=args.lockfile_path,
        with_tray=args.with_tray,
        with_runtime_dlls=args.with_runtime_dlls,
        with_packaging_support=args.with_packaging_support,
        dependency_sources=_dependency_sources_from_args(args),
    )
    return run_conan_lockfile_update(options, runner, execute=args.execute)


def _handle_conan_recipe_validate(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = ConanRecipeValidationOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        host_profile_path=args.host_profile_path,
        build_profile=args.build_profile,
        dependency_sources=_dependency_sources_from_args(args),
        openssl_linkage=ConanDependencyLinkage(args.openssl_linkage),
    )
    return run_conan_recipe_validation(options, runner, execute=args.execute)


def _handle_bundle_package(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = BundlePackageOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        build_root=args.build_root,
        squid_stage_root=args.squid_stage_root,
        artifact_root=args.artifact_root,
        installer_project_path=args.installer_project_path,
        create_portable_zip=args.create_portable_zip,
        sign_payload_files=args.sign_payload_files,
        require_tray=args.require_tray,
        require_notices=args.require_notices,
        build_installer=not args.skip_installer,
        product_version=args.product_version,
        service_name=args.service_name,
        sign_msi=args.sign_msi,
        dependency_sources=_dependency_sources_from_args(args),
    )
    return run_bundle_package(options, runner, execute=args.execute)


def _handle_smoke_test(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = SmokeTestOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        build_root=args.build_root,
        squid_stage_root=args.squid_stage_root,
        metadata_path=args.metadata_path,
        binary_path=args.binary_path,
        require_notices=args.require_notices,
    )
    return run_smoke_test(options, runner, execute=args.execute)


def _handle_service_runner_validation(
    args: argparse.Namespace,
    runner: PlanRunner,
) -> int:
    options = ServiceRunnerValidationOptions(
        repository_root=args.repository_root,
        configuration=args.configuration,
        build_root=args.build_root,
        artifact_root=args.artifact_root,
        service_name=args.service_name,
        service_name_prefix=args.service_name_prefix,
        install_root=args.install_root,
        service_timeout_seconds=args.service_timeout_seconds,
        allow_non_runner_execution=args.allow_non_runner_execution,
        dependency_sources=_dependency_sources_from_args(args),
    )
    return run_service_runner_validation(options, runner, execute=args.execute)


def _handle_package_manager_export(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = PackageManagerExportOptions(
        repository_root=args.repository_root,
        version=args.version,
        tag=args.tag,
        repository=args.repository,
        msi_path=args.msi_path,
        portable_zip_path=args.portable_zip_path,
        output_root=args.output_root,
        package_identifier=args.package_identifier,
        package_name=args.package_name,
        publisher=args.publisher,
        publisher_url=args.publisher_url,
        package_url=args.package_url,
        msi_url=args.msi_url,
        portable_zip_url=args.portable_zip_url,
    )
    return run_package_manager_export(options, runner, execute=args.execute)


def _handle_publish_winget(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = PublishWingetOptions(
        repository_root=args.repository_root,
        version=args.version,
        tag=args.tag,
        repository=args.repository,
        manifest_root=args.manifest_root,
        package_identifier=args.package_identifier,
        target_repository=args.target_repository,
        base_branch=args.base_branch,
        working_root=args.working_root,
    )
    return run_publish_winget(options, runner, execute=args.execute)


def _handle_publish_chocolatey(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = PublishChocolateyOptions(
        repository_root=args.repository_root,
        version=args.version,
        package_root=args.package_root,
        package_id=args.package_id,
        push_source=args.push_source,
        query_source=args.query_source,
        output_root=args.output_root,
    )
    return run_publish_chocolatey(options, runner, execute=args.execute)


def _handle_publish_scoop(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = PublishScoopOptions(
        repository_root=args.repository_root,
        version=args.version,
        tag=args.tag,
        repository=args.repository,
        manifest_root=args.manifest_root,
        target_repository=args.target_repository,
        base_branch=args.base_branch,
        package_file_name=args.package_file_name,
        working_root=args.working_root,
    )
    return run_publish_scoop(options, runner, execute=args.execute)


def _handle_upstream_version(args: argparse.Namespace, runner: PlanRunner) -> int:
    options = UpstreamVersionOptions(
        repository_root=args.repository_root,
        metadata_path=args.metadata_path,
        config_path=args.config_path,
        conan_data_path=args.conan_data_path,
        repository=args.repository,
        major_version=args.major_version,
        include_prerelease=args.include_prerelease,
        version=args.version,
        tag=args.tag,
        published_at=args.published_at,
        source_archive=args.source_archive,
        source_signature=args.source_signature,
        source_archive_sha256=args.source_archive_sha256,
    )

    _ = runner
    logger = get_logger("squid4win.upstream")
    if options.version is None:
        with GitHubReleaseClient() as client:
            resolved_release = client.resolve_release(
                options.repository,
                major_version=options.major_version,
                include_prerelease=options.include_prerelease,
            )
        logger.info(
            "Selected upstream release %s (%s).",
            resolved_release.version,
            resolved_release.tag,
        )
        if resolved_release.html_url is not None:
            logger.info("Release page: %s", resolved_release.html_url)
        release = TargetUpstreamRelease.from_resolved_release(resolved_release)
    else:
        release = TargetUpstreamRelease.from_options(options)
        logger.info("Using explicit upstream release %s (%s).", release.version, release.tag)

    manager = UpstreamVersionManager(options, logger=logger)
    manager.synchronize(release, execute=args.execute)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    configure_logging(args.log_level, force=True)
    logger = get_logger("squid4win")
    github_context = github_actions_context()
    if github_context.enabled:
        logger.debug(
            "GitHub Actions context detected for %s at %s (%s on %s).",
            github_context.repository or "<unknown-repository>",
            github_context.workspace or "<unknown-workspace>",
            github_context.event_name or "<unknown-event>",
            github_context.ref_name or github_context.ref or "<unknown-ref>",
        )
        logger.debug(
            "GitHub run %s attempt %s action=%s pr=%s base=%s head=%s outputs=%s summary=%s.",
            github_context.run_number or "<unknown-run>",
            github_context.run_attempt or "<unknown-attempt>",
            github_context.event_action or "<none>",
            github_context.pull_request_number or "<none>",
            github_context.base_ref or github_context.base_sha or "<none>",
            github_context.head_ref or github_context.head_sha or "<none>",
            github_context.output_path or "<none>",
            github_context.step_summary_path or "<none>",
        )

    runner = PlanRunner(logger)
    try:
        return args.handler(args, runner)
    except ValidationError as error:
        logger.error("%s", error)
        return 2
    except (
        LookupError,
        OSError,
        PlanExecutionError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        logger.error("%s", error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        logger.error("Unhandled automation failure: %s", error)
        logger.debug("Unhandled automation failure details.", exc_info=error)
        return 1
