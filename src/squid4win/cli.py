from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import click
import httpx
import typer
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from squid4win.commands import (
    run_bundle_package,
    run_conan_lockfile_update,
    run_conan_recipe_artifact_staging,
    run_conan_recipe_validation,
    run_service_runner_validation,
    run_smoke_test,
    run_squid_build,
    run_tray_build,
)
from squid4win.logging_utils import configure_logging, get_logger, level_name_from_verbosity
from squid4win.models import (
    BuildConfiguration,
    BundlePackageOptions,
    ConanDependencyLinkage,
    ConanLockfileUpdateOptions,
    ConanRecipeArtifactStageOptions,
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
    default_make_jobs,
)
from squid4win.package_managers import (
    run_package_manager_export,
    run_publish_chocolatey,
    run_publish_scoop,
    run_publish_winget,
)
from squid4win.runner import PlanExecutionError, PlanRunner
from squid4win.skill_frontmatter import lint_repo_owned_skills
from squid4win.upstream import GitHubReleaseClient
from squid4win.utils.actions import context as github_actions_context
from squid4win.version_helper import TargetUpstreamRelease, UpstreamVersionManager

_DEFAULT_REPOSITORY = "jan-guenter/squid4win"
_CONSOLE = Console()
_INTERACTIVE_CANCEL = "cancel"
_INTERACTIVE_RUN = "run"
_HTTP_URL_OPTION_ADAPTER = TypeAdapter(AnyHttpUrl)

app = typer.Typer(
    name="squid4win-automation",
    help=(
        "Python automation foundation for squid4win. Commands execute by default; "
        "use --dry-run to preview and repeated -v/-q flags per command to adjust logging."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
)

RepositoryRootOption = Annotated[
    Path | None,
    typer.Option(
        "--repository-root",
        help="Override the detected repository root.",
    ),
]
DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run",
        is_flag=True,
        help="Log the planned work instead of executing it.",
    ),
]
ExecuteCompatOption = Annotated[
    bool,
    typer.Option(
        "--execute",
        is_flag=True,
        hidden=True,
        help="Deprecated compatibility alias. Commands execute by default.",
    ),
]
VerboseOption = Annotated[
    int,
    typer.Option(
        "-v",
        "--verbose",
        count=True,
        help="Increase logging verbosity. Repeatable; output clamps at DEBUG.",
    ),
]
QuietOption = Annotated[
    int,
    typer.Option(
        "-q",
        "--quiet",
        count=True,
        help="Reduce logging verbosity. Repeat for WARNING, ERROR, then CRITICAL output.",
    ),
]
ConfigurationOption = Annotated[BuildConfiguration, typer.Option("--configuration")]
BuildRootOption = Annotated[Path | None, typer.Option("--build-root")]
MetadataPathOption = Annotated[Path | None, typer.Option("--metadata-path")]
HostProfilePathOption = Annotated[Path | None, typer.Option("--host-profile-path")]
BuildProfileOption = Annotated[str, typer.Option("--build-profile")]
LockfilePathOption = Annotated[Path | None, typer.Option("--lockfile-path")]
ArtifactRootOption = Annotated[Path | None, typer.Option("--artifact-root")]
CompilerLabelOption = Annotated[str | None, typer.Option("--compiler-label")]
OpenSSLLinkageOption = Annotated[
    ConanDependencyLinkage,
    typer.Option("--openssl-linkage"),
]
WithTrayOption = Annotated[bool, typer.Option("--with-tray", is_flag=True)]
WithRuntimeDllsOption = Annotated[
    bool,
    typer.Option("--with-runtime-dlls", is_flag=True),
]
WithPackagingSupportOption = Annotated[
    bool,
    typer.Option("--with-packaging-support", is_flag=True),
]
OpenSSLSourceOption = Annotated[DependencySource, typer.Option("--openssl-source")]
Libxml2SourceOption = Annotated[DependencySource, typer.Option("--libxml2-source")]
Pcre2SourceOption = Annotated[DependencySource, typer.Option("--pcre2-source")]
ZlibSourceOption = Annotated[DependencySource, typer.Option("--zlib-source")]


@dataclass(frozen=True)
class CommandRuntime:
    runner: PlanRunner
    execute: bool


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    if ctx.resilient_parsing:
        return
    if ctx.invoked_subcommand is not None:
        return

    if _supports_interactive_selector():
        _run_interactive_selector()
        raise typer.Exit(0)

    typer.echo(ctx.get_help())
    raise typer.Exit(0)


def _supports_interactive_selector() -> bool:
    github_context = github_actions_context()
    ci_flag = os.getenv("CI", "")
    return (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and not github_context.enabled
        and ci_flag.lower() not in {"1", "true", "yes"}
    )


def _log_github_context(logger: Any) -> None:
    github_context = github_actions_context()
    if not github_context.enabled:
        return

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


def _build_runtime(
    *,
    verbose: int,
    quiet: int,
    dry_run: bool,
    execute_compat: bool,
) -> CommandRuntime:
    if dry_run and execute_compat:
        msg = "Use either --dry-run or --execute, not both."
        raise typer.BadParameter(msg, param_hint="--dry-run")

    configure_logging(level_name_from_verbosity(verbose=verbose, quiet=quiet), force=True)
    logger = get_logger("squid4win")
    _log_github_context(logger)
    if execute_compat:
        logger.warning(
            "--execute is deprecated because commands execute by default. "
            "Use --dry-run to preview work."
        )

    return CommandRuntime(runner=PlanRunner(logger), execute=not dry_run)


def _run_command(
    runtime: CommandRuntime,
    func: Any,
    options: Any,
) -> None:
    result = func(options, runtime.runner, execute=runtime.execute)
    if result:
        raise typer.Exit(result)


def _dependency_sources(
    *,
    openssl_source: DependencySource,
    libxml2_source: DependencySource,
    pcre2_source: DependencySource,
    zlib_source: DependencySource,
) -> NativeDependencySourceOptions:
    return NativeDependencySourceOptions(
        openssl_source=openssl_source,
        libxml2_source=libxml2_source,
        pcre2_source=pcre2_source,
        zlib_source=zlib_source,
    )


def _validated_http_url_option(*, value: str | None, option_name: str) -> AnyHttpUrl | None:
    if value is None:
        return None

    try:
        return _HTTP_URL_OPTION_ADAPTER.validate_python(value)
    except ValidationError as error:
        message = error.errors()[0]["msg"]
        raise typer.BadParameter(message, param_hint=option_name) from error


def _primary_option_name(param: click.Parameter) -> str:
    if isinstance(param, click.Option):
        long_options = [option for option in param.opts if option.startswith("--")]
        if long_options:
            return long_options[0]
        if param.opts:
            return param.opts[0]
    return param.name or "<unknown>"


def _interactive_display_value(param: click.Parameter, overrides: dict[str, object]) -> str:
    if param.name in overrides:
        value = overrides[param.name]
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "<empty>"
        return str(value)

    default = getattr(param, "default", None)
    if default in (None, ()):
        return "<required>" if getattr(param, "required", False) else "<default>"
    if isinstance(default, tuple):
        return ", ".join(str(item) for item in default)
    return str(default)


def _prompt_for_param(param: click.Parameter, current_value: str) -> object | None:
    label = _primary_option_name(param)
    if isinstance(param, click.Option) and param.hidden:
        return None

    if isinstance(param, click.Option) and param.is_flag:
        default = current_value.lower() in {"true", "1", "yes"}
        return Confirm.ask(f"Enable {label}?", default=default)

    if isinstance(param, click.Option) and isinstance(param.type, click.Choice):
        default = None if current_value.startswith("<") else current_value
        choices = [str(choice) for choice in param.type.choices]
        return Prompt.ask(
            f"Value for {label}",
            choices=choices,
            default=default,
            show_choices=False,
        )

    if isinstance(param, click.Option) and param.multiple:
        raw_value = Prompt.ask(
            f"Values for {label} (comma-separated, blank to clear)",
            default="" if current_value.startswith("<") else current_value,
        ).strip()
        if not raw_value:
            return []
        return [item.strip() for item in raw_value.split(",") if item.strip()]

    if isinstance(param, click.Option) and param.type is click.INT:
        default = None if current_value.startswith("<") else current_value
        return IntPrompt.ask(f"Value for {label}", default=int(default) if default else None)

    default = None if current_value.startswith("<") else current_value
    value = Prompt.ask(f"Value for {label}", default=default)
    return value.strip() if isinstance(value, str) else ""


def _render_interactive_args(command: click.Command, overrides: dict[str, object]) -> list[str]:
    args: list[str] = [command.name or ""]
    for param in command.params:
        if not isinstance(param, click.Option) or param.hidden or param.name not in overrides:
            continue

        option_name = _primary_option_name(param)
        value = overrides[param.name]
        if param.is_flag:
            if value:
                args.append(option_name)
            continue

        if param.multiple:
            for item in value if isinstance(value, list) else []:
                args.extend((option_name, str(item)))
            continue

        args.extend((option_name, str(value)))

    return args


def _run_interactive_selector() -> None:
    click_app = typer.main.get_command(app)
    if not isinstance(click_app, click.Group):
        return

    commands = {name: command for name, command in click_app.commands.items() if not command.hidden}
    if not commands:
        return

    overview = Table(title="squid4win-automation")
    overview.add_column("Command")
    overview.add_column("Summary")
    for name, command in sorted(commands.items()):
        overview.add_row(name, command.get_short_help_str() or "")
    _CONSOLE.print(Panel.fit("Interactive command selector", border_style="cyan"))
    _CONSOLE.print(overview)

    selected_name = Prompt.ask(
        "Choose a command",
        choices=sorted(commands),
        default="squid-build",
        show_choices=False,
    )
    selected_command = commands[selected_name]
    overrides: dict[str, object] = {}

    while True:
        option_table = Table(title=f"{selected_name} options")
        option_table.add_column("Option")
        option_table.add_column("Current")
        option_table.add_column("Required")
        option_table.add_column("Help")

        editable_params = [
            param
            for param in selected_command.params
            if isinstance(param, click.Option) and not param.hidden
        ]
        missing_required: list[str] = []
        param_by_option: dict[str, click.Option] = {}
        for param in editable_params:
            option_name = _primary_option_name(param)
            current_value = _interactive_display_value(param, overrides)
            required_text = "yes" if param.required else "no"
            if param.required and current_value == "<required>":
                missing_required.append(option_name)
            option_table.add_row(
                option_name,
                current_value,
                required_text,
                param.help or "",
            )
            param_by_option[option_name] = param

        _CONSOLE.print(option_table)
        action = Prompt.ask(
            "Choose an option to edit, or run/cancel",
            choices=[*sorted(param_by_option), _INTERACTIVE_RUN, _INTERACTIVE_CANCEL],
            default=_INTERACTIVE_RUN if not missing_required else sorted(param_by_option)[0],
            show_choices=False,
        )
        if action == _INTERACTIVE_CANCEL:
            return
        if action == _INTERACTIVE_RUN:
            if missing_required:
                _CONSOLE.print(
                    Panel.fit(
                        f"Set required options before running: {', '.join(missing_required)}",
                        border_style="red",
                    )
                )
                continue
            command_args = _render_interactive_args(selected_command, overrides)
            app(
                args=command_args,
                prog_name="squid4win-automation",
                standalone_mode=False,
            )
            return

        selected_param = param_by_option[action]
        current_value = _interactive_display_value(selected_param, overrides)
        prompted_value = _prompt_for_param(selected_param, current_value)
        if prompted_value in ("", None):
            overrides.pop(selected_param.name or "", None)
            continue
        overrides[selected_param.name or ""] = prompted_value


@app.command(
    "squid-build",
    help=(
        "Run or preview the CCI-style Squid recipe build from conan\\recipes\\squid\\all "
        "with native Python orchestration."
    ),
)
def squid_build(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    build_root: BuildRootOption = None,
    metadata_path: MetadataPathOption = None,
    host_profile_path: HostProfilePathOption = None,
    build_profile: BuildProfileOption = "default",
    lockfile_path: LockfilePathOption = None,
    additional_configure_arg: Annotated[
        list[str] | None,
        typer.Option("--additional-configure-arg"),
    ] = None,
    make_jobs: Annotated[
        int,
        typer.Option(
            "--make-jobs",
            min=1,
            max=1024,
            show_default=f"auto ({default_make_jobs()})",
        ),
    ] = default_make_jobs(),
    bootstrap_only: Annotated[bool, typer.Option("--bootstrap-only", is_flag=True)] = False,
    refresh_lockfile: Annotated[bool, typer.Option("--refresh-lockfile", is_flag=True)] = False,
    clean: Annotated[bool, typer.Option("--clean", is_flag=True)] = False,
    with_tray: WithTrayOption = False,
    with_runtime_dlls: WithRuntimeDllsOption = False,
    with_packaging_support: WithPackagingSupportOption = False,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = SquidBuildOptions(
        repository_root=repository_root,
        configuration=configuration,
        build_root=build_root,
        metadata_path=metadata_path,
        host_profile_path=host_profile_path,
        build_profile=build_profile,
        lockfile_path=lockfile_path,
        additional_configure_args=tuple(additional_configure_arg or ()),
        make_jobs=make_jobs,
        bootstrap_only=bootstrap_only,
        refresh_lockfile=refresh_lockfile,
        clean=clean,
        with_tray=with_tray,
        with_runtime_dlls=with_runtime_dlls,
        with_packaging_support=with_packaging_support,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
    )
    _run_command(runtime, run_squid_build, options)


@app.command(
    "tray-build",
    help="Run or preview the direct .NET tray build with native Python orchestration.",
)
def tray_build(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    publish_root: Annotated[Path | None, typer.Option("--publish-root")] = None,
    package_root: Annotated[
        Path | None,
        typer.Option("--package-root", "--output-root"),
    ] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = TrayBuildOptions(
        repository_root=repository_root,
        configuration=configuration,
        publish_root=publish_root,
        package_root=package_root,
    )
    _run_command(runtime, run_tray_build, options)


@app.command(
    "conan-lockfile-update",
    help="Run or preview Conan lockfile refresh with native Python orchestration.",
)
def conan_lockfile_update(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    build_root: BuildRootOption = None,
    host_profile_path: HostProfilePathOption = None,
    build_profile: BuildProfileOption = "default",
    lockfile_path: LockfilePathOption = None,
    with_tray: WithTrayOption = False,
    with_runtime_dlls: WithRuntimeDllsOption = False,
    with_packaging_support: WithPackagingSupportOption = False,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = ConanLockfileUpdateOptions(
        repository_root=repository_root,
        configuration=configuration,
        build_root=build_root,
        host_profile_path=host_profile_path,
        build_profile=build_profile,
        lockfile_path=lockfile_path,
        with_tray=with_tray,
        with_runtime_dlls=with_runtime_dlls,
        with_packaging_support=with_packaging_support,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
    )
    _run_command(runtime, run_conan_lockfile_update, options)


@app.command(
    "conan-recipe-validate",
    help="Run or preview conan create validation for the standalone Squid recipe.",
)
def conan_recipe_validate(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    host_profile_path: HostProfilePathOption = None,
    build_profile: BuildProfileOption = "default",
    openssl_linkage: OpenSSLLinkageOption = ConanDependencyLinkage.DEFAULT,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = ConanRecipeValidationOptions(
        repository_root=repository_root,
        configuration=configuration,
        host_profile_path=host_profile_path,
        build_profile=build_profile,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
        openssl_linkage=openssl_linkage,
    )
    _run_command(runtime, run_conan_recipe_validation, options)


@app.command(
    "conan-recipe-stage-artifacts",
    help="Stage or preview the latest Conan recipe validation cache outputs under artifacts/.",
)
def conan_recipe_stage_artifacts(
    library_configuration_label: Annotated[
        str,
        typer.Option("--library-configuration-label"),
    ],
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    artifact_root: ArtifactRootOption = None,
    host_profile_path: HostProfilePathOption = None,
    compiler_label: CompilerLabelOption = None,
    openssl_linkage: OpenSSLLinkageOption = ConanDependencyLinkage.DEFAULT,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = ConanRecipeArtifactStageOptions(
        repository_root=repository_root,
        artifact_root=artifact_root,
        configuration=configuration,
        host_profile_path=host_profile_path,
        compiler_label=compiler_label,
        library_configuration_label=library_configuration_label,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
        openssl_linkage=openssl_linkage,
    )
    _run_command(runtime, run_conan_recipe_artifact_staging, options)


@app.command(
    "bundle-package",
    help=(
        "Run or preview payload staging, installer packaging, and any missing prerequisite builds."
    ),
)
def bundle_package(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    build_root: BuildRootOption = None,
    squid_stage_root: Annotated[Path | None, typer.Option("--squid-stage-root")] = None,
    artifact_root: ArtifactRootOption = None,
    installer_project_path: Annotated[Path | None, typer.Option("--installer-project-path")] = None,
    create_portable_zip: Annotated[
        bool, typer.Option("--create-portable-zip", is_flag=True)
    ] = False,
    sign_payload_files: Annotated[bool, typer.Option("--sign-payload-files", is_flag=True)] = False,
    require_tray: Annotated[bool, typer.Option("--require-tray", is_flag=True)] = False,
    require_notices: Annotated[bool, typer.Option("--require-notices", is_flag=True)] = False,
    skip_installer: Annotated[bool, typer.Option("--skip-installer", is_flag=True)] = False,
    product_version: Annotated[str | None, typer.Option("--product-version")] = None,
    service_name: Annotated[str, typer.Option("--service-name")] = "Squid4Win",
    sign_msi: Annotated[bool, typer.Option("--sign-msi", is_flag=True)] = False,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = BundlePackageOptions(
        repository_root=repository_root,
        configuration=configuration,
        build_root=build_root,
        squid_stage_root=squid_stage_root,
        artifact_root=artifact_root,
        installer_project_path=installer_project_path,
        create_portable_zip=create_portable_zip,
        sign_payload_files=sign_payload_files,
        require_tray=require_tray,
        require_notices=require_notices,
        build_installer=not skip_installer,
        product_version=product_version,
        service_name=service_name,
        sign_msi=sign_msi,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
    )
    _run_command(runtime, run_bundle_package, options)


@app.command(
    "smoke-test",
    help="Run or preview staged-bundle validation for Squid, runtime DLLs, and notices.",
)
def smoke_test(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    build_root: BuildRootOption = None,
    squid_stage_root: Annotated[Path | None, typer.Option("--squid-stage-root")] = None,
    metadata_path: MetadataPathOption = None,
    binary_path: Annotated[Path | None, typer.Option("--binary-path")] = None,
    require_notices: Annotated[bool, typer.Option("--require-notices", is_flag=True)] = False,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = SmokeTestOptions(
        repository_root=repository_root,
        configuration=configuration,
        build_root=build_root,
        squid_stage_root=squid_stage_root,
        metadata_path=metadata_path,
        binary_path=binary_path,
        require_notices=require_notices,
    )
    _run_command(runtime, run_smoke_test, options)


@app.command(
    "service-runner-validation",
    help="Run or preview MSI-installed Windows service lifecycle validation.",
)
def service_runner_validation(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    configuration: ConfigurationOption = BuildConfiguration.RELEASE,
    build_root: BuildRootOption = None,
    artifact_root: ArtifactRootOption = None,
    service_name: Annotated[str | None, typer.Option("--service-name")] = None,
    service_name_prefix: Annotated[str, typer.Option("--service-name-prefix")] = "Squid4WinRunner",
    install_root: Annotated[Path | None, typer.Option("--install-root")] = None,
    service_timeout_seconds: Annotated[
        int,
        typer.Option("--service-timeout-seconds", min=1, max=600),
    ] = 60,
    allow_non_runner_execution: Annotated[
        bool,
        typer.Option("--allow-non-runner-execution", is_flag=True),
    ] = False,
    openssl_source: OpenSSLSourceOption = DependencySource.SYSTEM,
    libxml2_source: Libxml2SourceOption = DependencySource.SYSTEM,
    pcre2_source: Pcre2SourceOption = DependencySource.SYSTEM,
    zlib_source: ZlibSourceOption = DependencySource.SYSTEM,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = ServiceRunnerValidationOptions(
        repository_root=repository_root,
        configuration=configuration,
        build_root=build_root,
        artifact_root=artifact_root,
        service_name=service_name,
        service_name_prefix=service_name_prefix,
        install_root=install_root,
        service_timeout_seconds=service_timeout_seconds,
        allow_non_runner_execution=allow_non_runner_execution,
        dependency_sources=_dependency_sources(
            openssl_source=openssl_source,
            libxml2_source=libxml2_source,
            pcre2_source=pcre2_source,
            zlib_source=zlib_source,
        ),
    )
    _run_command(runtime, run_service_runner_validation, options)


@app.command(
    "package-manager-export",
    help="Run or preview winget, Chocolatey, and Scoop metadata generation from released binaries.",
)
def package_manager_export(
    version: Annotated[str, typer.Option("--version")],
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    repository: Annotated[str, typer.Option("--repository")] = _DEFAULT_REPOSITORY,
    msi_path: Annotated[Path | None, typer.Option("--msi-path")] = None,
    portable_zip_path: Annotated[Path | None, typer.Option("--portable-zip-path")] = None,
    output_root: Annotated[Path | None, typer.Option("--output-root")] = None,
    package_identifier: Annotated[
        str, typer.Option("--package-identifier")
    ] = "JanGuenter.Squid4Win",
    package_name: Annotated[str, typer.Option("--package-name")] = "Squid4Win",
    publisher: Annotated[str, typer.Option("--publisher")] = "Jan Guenter",
    publisher_url: Annotated[
        str, typer.Option("--publisher-url")
    ] = "https://github.com/jan-guenter",
    package_url: Annotated[str | None, typer.Option("--package-url")] = None,
    msi_url: Annotated[str | None, typer.Option("--msi-url")] = None,
    portable_zip_url: Annotated[str | None, typer.Option("--portable-zip-url")] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = PackageManagerExportOptions(
        repository_root=repository_root,
        version=version,
        tag=tag,
        repository=repository,
        msi_path=msi_path,
        portable_zip_path=portable_zip_path,
        output_root=output_root,
        package_identifier=package_identifier,
        package_name=package_name,
        publisher=publisher,
        publisher_url=publisher_url,
        package_url=package_url,
        msi_url=msi_url,
        portable_zip_url=portable_zip_url,
    )
    _run_command(runtime, run_package_manager_export, options)


@app.command(
    "publish-winget",
    help="Run or preview winget publication through a GitHub pull request.",
)
def publish_winget(
    version: Annotated[str, typer.Option("--version")],
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    repository: Annotated[str, typer.Option("--repository")] = _DEFAULT_REPOSITORY,
    manifest_root: Annotated[Path | None, typer.Option("--manifest-root")] = None,
    package_identifier: Annotated[
        str, typer.Option("--package-identifier")
    ] = "JanGuenter.Squid4Win",
    target_repository: Annotated[
        str, typer.Option("--target-repository")
    ] = "microsoft/winget-pkgs",
    base_branch: Annotated[str, typer.Option("--base-branch")] = "master",
    working_root: Annotated[Path | None, typer.Option("--working-root")] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = PublishWingetOptions(
        repository_root=repository_root,
        version=version,
        tag=tag,
        repository=repository,
        manifest_root=manifest_root,
        package_identifier=package_identifier,
        target_repository=target_repository,
        base_branch=base_branch,
        working_root=working_root,
    )
    _run_command(runtime, run_publish_winget, options)


@app.command(
    "publish-chocolatey",
    help="Run or preview Chocolatey package publication.",
)
def publish_chocolatey(
    version: Annotated[str, typer.Option("--version")],
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    package_root: Annotated[Path | None, typer.Option("--package-root")] = None,
    package_id: Annotated[str, typer.Option("--package-id")] = "squid4win",
    push_source: Annotated[str, typer.Option("--push-source")] = "https://push.chocolatey.org/",
    query_source: Annotated[
        str, typer.Option("--query-source")
    ] = "https://community.chocolatey.org/api/v2/",
    output_root: Annotated[Path | None, typer.Option("--output-root")] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = PublishChocolateyOptions(
        repository_root=repository_root,
        version=version,
        package_root=package_root,
        package_id=package_id,
        push_source=push_source,
        query_source=query_source,
        output_root=output_root,
    )
    _run_command(runtime, run_publish_chocolatey, options)


@app.command(
    "publish-scoop",
    help="Run or preview Scoop manifest publication through a GitHub pull request.",
)
def publish_scoop(
    version: Annotated[str, typer.Option("--version")],
    target_repository: Annotated[str, typer.Option("--target-repository")],
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    repository: Annotated[str, typer.Option("--repository")] = _DEFAULT_REPOSITORY,
    manifest_root: Annotated[Path | None, typer.Option("--manifest-root")] = None,
    base_branch: Annotated[str, typer.Option("--base-branch")] = "master",
    package_file_name: Annotated[str, typer.Option("--package-file-name")] = "squid4win.json",
    working_root: Annotated[Path | None, typer.Option("--working-root")] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = PublishScoopOptions(
        repository_root=repository_root,
        version=version,
        tag=tag,
        repository=repository,
        manifest_root=manifest_root,
        target_repository=target_repository,
        base_branch=base_branch,
        package_file_name=package_file_name,
        working_root=working_root,
    )
    _run_command(runtime, run_publish_scoop, options)


@app.command(
    "upstream-version",
    help="Preview or apply upstream Squid version metadata synchronization.",
)
def upstream_version(
    repository_root: RepositoryRootOption = None,
    dry_run: DryRunOption = False,
    execute_compat: ExecuteCompatOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    metadata_path: Annotated[Path | None, typer.Option("--metadata-path")] = None,
    config_path: Annotated[Path | None, typer.Option("--config-path")] = None,
    conan_data_path: Annotated[Path | None, typer.Option("--conan-data-path")] = None,
    repository: Annotated[str, typer.Option("--repository")] = "squid-cache/squid",
    major_version: Annotated[int | None, typer.Option("--major-version", min=1)] = None,
    include_prerelease: Annotated[bool, typer.Option("--include-prerelease", is_flag=True)] = False,
    version: Annotated[str | None, typer.Option("--version")] = None,
    tag: Annotated[str | None, typer.Option("--tag")] = None,
    published_at: Annotated[str | None, typer.Option("--published-at")] = None,
    source_archive: Annotated[str | None, typer.Option("--source-archive")] = None,
    source_signature: Annotated[str | None, typer.Option("--source-signature")] = None,
    source_archive_sha256: Annotated[str | None, typer.Option("--source-archive-sha256")] = None,
) -> None:
    runtime = _build_runtime(
        verbose=verbose,
        quiet=quiet,
        dry_run=dry_run,
        execute_compat=execute_compat,
    )
    options = UpstreamVersionOptions(
        repository_root=repository_root,
        metadata_path=metadata_path,
        config_path=config_path,
        conan_data_path=conan_data_path,
        repository=repository,
        major_version=major_version,
        include_prerelease=include_prerelease,
        version=version,
        tag=tag,
        published_at=published_at,
        source_archive=_validated_http_url_option(
            value=source_archive,
            option_name="--source-archive",
        ),
        source_signature=_validated_http_url_option(
            value=source_signature,
            option_name="--source-signature",
        ),
        source_archive_sha256=source_archive_sha256,
    )

    _ = runtime.runner
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
    manager.synchronize(release, execute=runtime.execute)


@app.command(
    "skill-frontmatter-lint",
    help=(
        "Validate repo-owned skill SKILL.md frontmatter against the repo's "
        "Copilot-compatible contract."
    ),
)
def skill_frontmatter_lint(
    repository_root: RepositoryRootOption = None,
    verbose: VerboseOption = 0,
    quiet: QuietOption = 0,
    skills_root: Annotated[Path | None, typer.Option("--skills-root")] = None,
) -> None:
    configure_logging(level_name_from_verbosity(verbose=verbose, quiet=quiet), force=True)
    logger = get_logger("squid4win.skills")
    _log_github_context(logger)

    result = lint_repo_owned_skills(repository_root=repository_root, skills_root=skills_root)
    if result.issues:
        for issue in result.issues:
            logger.error("%s", issue)
        raise typer.Exit(1)

    logger.info(
        "Validated %d repo-owned skill(s) under %s.",
        len(result.validated_skills),
        result.skills_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        app(
            args=list(argv) if argv is not None else None,
            prog_name="squid4win-automation",
            standalone_mode=False,
        )
        return 0
    except typer.Exit as error:
        return int(error.exit_code)
    except click.ClickException as error:
        error.show()
        return int(error.exit_code)
    except ValidationError as error:
        configure_logging(force=False)
        logger = get_logger("squid4win")
        logger.error("%s", error)
        return 2
    except (
        LookupError,
        OSError,
        PlanExecutionError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        configure_logging(force=False)
        logger = get_logger("squid4win")
        logger.error("%s", error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        configure_logging(force=False)
        logger = get_logger("squid4win")
        logger.error("Unhandled automation failure: %s", error)
        logger.debug("Unhandled automation failure details.", exc_info=error)
        return 1
