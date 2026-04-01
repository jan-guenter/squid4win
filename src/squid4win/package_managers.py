from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx
import yaml

from squid4win.logging_utils import get_logger
from squid4win.models import (
    ChocolateyPublicationResult,
    GitHubPublicationResult,
    PackageManagerExportOptions,
    PackageManagerExportResult,
    PublishChocolateyOptions,
    PublishScoopOptions,
    PublishWingetOptions,
    RepositoryPaths,
)
from squid4win.paths import resolve_path

if TYPE_CHECKING:
    from squid4win.runner import PlanRunner

_WINGET_MANIFEST_VERSION = "1.9.0"
_LOGGER_NAME = "squid4win.package_managers"
_NUSPEC_XML_NAMESPACE = "http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd"
_ATOM_XML_NAMESPACE = "http://www.w3.org/2005/Atom"


@dataclass(frozen=True)
class PackageManagerExportContext:
    paths: RepositoryPaths
    version: str
    tag: str
    repository: str
    msi_path: Path
    portable_zip_path: Path
    output_root: Path
    package_identifier: str
    package_name: str
    publisher: str
    publisher_url: str
    package_url: str
    msi_url: str
    portable_zip_url: str
    license_url: str
    issues_url: str
    release_notes_url: str
    winget_root: Path
    chocolatey_root: Path
    chocolatey_tools_root: Path
    scoop_root: Path
    scoop_manifest_path: Path


def _resolved_or_default(value: Path | None, default: Path, *, base: Path) -> Path:
    return resolve_path(value, base=base) or default


def _sha256_hex(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(content, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def _yaml_text(document: dict[str, Any]) -> str:
    rendered = yaml.safe_dump(
        document,
        allow_unicode=False,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    return rendered


def _render_winget_documents(
    context: PackageManagerExportContext,
    *,
    msi_sha256: str,
) -> dict[Path, str]:
    version_path = context.winget_root / f"{context.package_identifier}.yaml"
    locale_path = context.winget_root / f"{context.package_identifier}.locale.en-US.yaml"
    installer_path = context.winget_root / f"{context.package_identifier}.installer.yaml"

    version_document = {
        "PackageIdentifier": context.package_identifier,
        "PackageVersion": context.version,
        "DefaultLocale": "en-US",
        "ManifestType": "version",
        "ManifestVersion": _WINGET_MANIFEST_VERSION,
    }
    locale_document = {
        "PackageIdentifier": context.package_identifier,
        "PackageVersion": context.version,
        "PackageLocale": "en-US",
        "Publisher": context.publisher,
        "PublisherUrl": context.publisher_url,
        "PublisherSupportUrl": context.issues_url,
        "PackageName": context.package_name,
        "PackageUrl": context.package_url,
        "ShortDescription": (
            "Windows-first native Squid packaging with an MSI installer and tray application."
        ),
        "License": "GPL-2.0-or-later",
        "LicenseUrl": context.license_url,
        "ReleaseNotesUrl": context.release_notes_url,
        "ManifestType": "defaultLocale",
        "ManifestVersion": _WINGET_MANIFEST_VERSION,
    }
    installer_document = {
        "PackageIdentifier": context.package_identifier,
        "PackageVersion": context.version,
        "InstallerType": "wix",
        "Scope": "machine",
        "UpgradeBehavior": "install",
        "InstallModes": ["interactive", "silent", "silentWithProgress"],
        "Commands": ["squid"],
        "Installers": [
            {
                "Architecture": "x64",
                "InstallerLocale": "en-US",
                "InstallerUrl": context.msi_url,
                "InstallerSha256": msi_sha256,
            }
        ],
        "ManifestType": "installer",
        "ManifestVersion": _WINGET_MANIFEST_VERSION,
    }

    return {
        version_path: _yaml_text(version_document),
        locale_path: _yaml_text(locale_document),
        installer_path: _yaml_text(installer_document),
    }


def _render_chocolatey_nuspec(context: PackageManagerExportContext) -> str:
    package_element = ElementTree.Element(
        "package",
        {"xmlns": _NUSPEC_XML_NAMESPACE},
    )
    metadata_element = ElementTree.SubElement(package_element, "metadata")
    for tag_name, value in (
        ("id", "squid4win"),
        ("version", context.version),
        ("title", context.package_name),
        ("authors", context.publisher),
        ("owners", context.publisher),
        ("projectUrl", context.package_url),
        ("licenseUrl", context.license_url),
        ("projectSourceUrl", context.package_url),
        ("docsUrl", context.package_url),
        ("bugTrackerUrl", context.issues_url),
        ("requireLicenseAcceptance", "false"),
        ("summary", "Windows-first native Squid packaging."),
        (
            "description",
            (
                "Installs the Squid4Win MSI built from the upstream Squid release "
                "and companion tray application."
            ),
        ),
        ("tags", "squid proxy windows msi tray"),
    ):
        element = ElementTree.SubElement(metadata_element, tag_name)
        element.text = value

    tree = ElementTree.ElementTree(package_element)
    ElementTree.indent(tree, space="  ")
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue().decode("utf-8") + "\n"


def _render_chocolatey_install_script(
    context: PackageManagerExportContext,
    *,
    msi_sha256: str,
) -> str:
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "",
        "$packageArgs = @{",
        "    packageName    = 'squid4win'",
        "    fileType       = 'msi'",
        "    softwareName   = 'Squid4Win*'",
        f"    url64bit       = '{context.msi_url}'",
        f"    checksum64     = '{msi_sha256}'",
        "    checksumType64 = 'sha256'",
        "    silentArgs     = '/qn /norestart'",
        "    validExitCodes = @(0, 3010, 1641)",
        "}",
        "",
        "Install-ChocolateyPackage @packageArgs",
        "",
    ]
    return "\n".join(lines)


def _render_scoop_manifest(
    context: PackageManagerExportContext,
    *,
    portable_zip_sha256: str,
) -> str:
    manifest = {
        "version": context.version,
        "description": (
            "Windows-first native Squid packaging with a portable zip and tray application."
        ),
        "homepage": context.package_url,
        "license": "GPL-2.0-or-later",
        "url": context.portable_zip_url,
        "hash": portable_zip_sha256,
        "bin": [
            "Squid4Win.Tray.exe",
            ["sbin\\squid.exe", "squid"],
        ],
        "shortcuts": [["Squid4Win.Tray.exe", "Squid4Win Tray"]],
        "checkver": {"github": context.package_url},
        "autoupdate": {
            "url": f"{context.package_url}/releases/download/v$version/squid4win-portable.zip"
        },
    }
    return json.dumps(manifest, indent=2) + "\n"


def _append_github_output(result: PackageManagerExportResult) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    lines = (
        f"output_root={result.output_root}",
        f"msi_sha256={result.msi_sha256}",
        f"portable_zip_sha256={result.portable_zip_sha256}",
        f"msi_url={result.msi_url}",
        f"portable_zip_url={result.portable_zip_url}",
    )
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _resolve_export_context(options: PackageManagerExportOptions) -> PackageManagerExportContext:
    paths = RepositoryPaths.discover(options.repository_root)
    repository_root = paths.repository_root
    msi_path = _resolved_or_default(
        options.msi_path,
        paths.artifact_root / "squid4win.msi",
        base=repository_root,
    )
    portable_zip_path = _resolved_or_default(
        options.portable_zip_path,
        paths.artifact_root / "squid4win-portable.zip",
        base=repository_root,
    )
    output_root = _resolved_or_default(
        options.output_root,
        paths.artifact_root / "package-managers",
        base=repository_root,
    )
    if not msi_path.is_file():
        msg = f"The MSI artifact '{msi_path}' was not found."
        raise FileNotFoundError(msg)
    if not portable_zip_path.is_file():
        msg = f"The portable zip artifact '{portable_zip_path}' was not found."
        raise FileNotFoundError(msg)

    tag = options.tag or f"v{options.version}"
    package_url = options.package_url or f"https://github.com/{options.repository}"
    msi_url = options.msi_url or f"{package_url}/releases/download/{tag}/squid4win.msi"
    portable_zip_url = (
        options.portable_zip_url
        or f"{package_url}/releases/download/{tag}/squid4win-portable.zip"
    )
    winget_root = output_root / "winget" / options.version
    chocolatey_root = output_root / "chocolatey"
    scoop_root = output_root / "scoop"

    return PackageManagerExportContext(
        paths=paths,
        version=options.version,
        tag=tag,
        repository=options.repository,
        msi_path=msi_path,
        portable_zip_path=portable_zip_path,
        output_root=output_root,
        package_identifier=options.package_identifier,
        package_name=options.package_name,
        publisher=options.publisher,
        publisher_url=options.publisher_url,
        package_url=package_url,
        msi_url=msi_url,
        portable_zip_url=portable_zip_url,
        license_url=f"{package_url}/blob/main/LICENSE",
        issues_url=f"{package_url}/issues",
        release_notes_url=f"{package_url}/releases/tag/{tag}",
        winget_root=winget_root,
        chocolatey_root=chocolatey_root,
        chocolatey_tools_root=chocolatey_root / "tools",
        scoop_root=scoop_root,
        scoop_manifest_path=scoop_root / "squid4win.json",
    )


def _build_export_result(context: PackageManagerExportContext) -> PackageManagerExportResult:
    return PackageManagerExportResult(
        output_root=context.output_root,
        winget_root=context.winget_root,
        chocolatey_root=context.chocolatey_root,
        scoop_manifest_path=context.scoop_manifest_path,
        msi_sha256=_sha256_hex(context.msi_path),
        portable_zip_sha256=_sha256_hex(context.portable_zip_path),
        msi_url=context.msi_url,
        portable_zip_url=context.portable_zip_url,
    )


def run_package_manager_export(
    options: PackageManagerExportOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    _ = runner
    logger = get_logger(_LOGGER_NAME)
    context = _resolve_export_context(options)
    result = _build_export_result(context)

    logger.info(
        "Generate package manager metadata for %s from %s and %s.",
        context.version,
        context.msi_path,
        context.portable_zip_path,
    )
    logger.info("Output root: %s", result.output_root)
    logger.info("MSI SHA256: %s", result.msi_sha256)
    logger.info("Portable zip SHA256: %s", result.portable_zip_sha256)

    if not execute:
        logger.info("Dry run only; package manager metadata files were not written.")
        return 0

    winget_documents = _render_winget_documents(context, msi_sha256=result.msi_sha256)
    for path, content in winget_documents.items():
        _write_text(path, content)

    _write_text(
        context.chocolatey_root / "squid4win.nuspec",
        _render_chocolatey_nuspec(context),
    )
    _write_text(
        context.chocolatey_tools_root / "chocolateyinstall.ps1",
        _render_chocolatey_install_script(context, msi_sha256=result.msi_sha256),
    )
    _write_text(
        context.scoop_manifest_path,
        _render_scoop_manifest(context, portable_zip_sha256=result.portable_zip_sha256),
    )
    _append_github_output(result)

    logger.info("Winget manifest root: %s", result.winget_root)
    logger.info("Chocolatey package root: %s", result.chocolatey_root)
    logger.info("Scoop manifest path: %s", result.scoop_manifest_path)
    return 0


def _command_line(command: tuple[str, ...]) -> str:
    return subprocess.list2cmdline(list(command))


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> str:
    logger = get_logger(_LOGGER_NAME)
    logger.debug("RUN: %s", _command_line(command))
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part is not None and part.strip()
    ).strip()
    if check and completed.returncode != 0:
        msg = output or f"{command[0]} exited with code {completed.returncode}."
        raise RuntimeError(msg)
    return output


def _command_succeeds(
    command: tuple[str, ...],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        msg = f"The '{name}' command is required but was not found on PATH."
        raise FileNotFoundError(msg)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            target = destination / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _get_open_pull_request_url(
    repository: str,
    head: str,
    *,
    env: dict[str, str],
) -> str | None:
    pull_request_url = _run_command(
        (
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--head",
            head,
            "--json",
            "url",
            "--jq",
            ".[0].url",
        ),
        env=env,
    )
    if pull_request_url in ("", "null"):
        return None
    return pull_request_url


def _submit_github_pull_request(
    *,
    source_path: Path,
    destination_repository: str,
    destination_path: str,
    branch_name: str,
    commit_message: str,
    pull_request_title: str,
    pull_request_body: str,
    base_branch: str,
    working_root: Path,
) -> GitHubPublicationResult:
    _require_command("gh")
    _require_command("git")

    env = os.environ.copy()
    login = _run_command(("gh", "api", "user", "--jq", ".login"), env=env)
    if not login:
        msg = "Unable to resolve the authenticated GitHub login from gh."
        raise RuntimeError(msg)

    target_owner, target_repository_name = destination_repository.split("/", 1)
    use_fork = target_owner != login
    head_repository = f"{login}/{target_repository_name}" if use_fork else destination_repository
    head_selector = f"{login}:{branch_name}" if use_fork else branch_name
    clone_name = re.sub(r"[^A-Za-z0-9._-]", "-", f"{destination_repository}-{branch_name}")
    clone_path = working_root / clone_name
    destination_relative_path = destination_path.lstrip("\\/")
    destination_pure_path = PurePosixPath(destination_relative_path.replace("\\", "/"))

    try:
        if use_fork and not _command_succeeds(
            (
                "gh",
                "repo",
                "view",
                head_repository,
                "--json",
                "nameWithOwner",
                "--jq",
                ".nameWithOwner",
            ),
            env=env,
        ):
            _run_command(
                ("gh", "repo", "fork", destination_repository, "--clone=false", "--remote=false"),
                env=env,
            )

        if use_fork:
            fork_ready = False
            for _ in range(20):
                if _command_succeeds(
                    (
                        "gh",
                        "repo",
                        "view",
                        head_repository,
                        "--json",
                        "nameWithOwner",
                        "--jq",
                        ".nameWithOwner",
                    ),
                    env=env,
                ):
                    fork_ready = True
                    break
                time.sleep(3)

            if not fork_ready:
                msg = f"The fork '{head_repository}' was not ready after creation."
                raise RuntimeError(msg)

        working_root.mkdir(parents=True, exist_ok=True)
        if clone_path.exists():
            shutil.rmtree(clone_path)

        _run_command(("gh", "auth", "setup-git"), env=env)
        _run_command(
            (
                "git",
                "clone",
                "--quiet",
                "--filter=blob:none",
                "--no-checkout",
                f"https://github.com/{destination_repository}.git",
                str(clone_path),
            ),
            env=env,
        )

        if source_path.is_dir():
            sparse_path = destination_pure_path.as_posix()
        else:
            parent_path = destination_pure_path.parent.as_posix()
            sparse_path = (
                parent_path if parent_path not in ("", ".") else destination_pure_path.as_posix()
            )

        _run_command(("git", "-C", str(clone_path), "sparse-checkout", "init", "--cone"), env=env)
        _run_command(
            ("git", "-C", str(clone_path), "sparse-checkout", "set", sparse_path),
            env=env,
        )
        _run_command(("git", "-C", str(clone_path), "checkout", base_branch), env=env)

        if use_fork:
            _run_command(
                (
                    "git",
                    "-C",
                    str(clone_path),
                    "remote",
                    "add",
                    "fork",
                    f"https://github.com/{head_repository}.git",
                ),
                env=env,
            )

        _run_command(
            ("git", "-C", str(clone_path), "config", "user.name", "github-actions[bot]"),
            env=env,
        )
        _run_command(
            (
                "git",
                "-C",
                str(clone_path),
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ),
            env=env,
        )
        _run_command(("git", "-C", str(clone_path), "checkout", "-B", branch_name), env=env)

        destination_full_path = clone_path.joinpath(*destination_pure_path.parts)
        _copy_path(source_path, destination_full_path)

        git_path_spec = destination_pure_path.as_posix()
        _run_command(
            ("git", "-C", str(clone_path), "add", "--all", "--", git_path_spec),
            env=env,
        )
        status = _run_command(
            ("git", "-C", str(clone_path), "status", "--porcelain", "--", git_path_spec),
            env=env,
        )
        pull_request_url = _get_open_pull_request_url(
            destination_repository,
            head_selector,
            env=env,
        )
        if not status:
            return GitHubPublicationResult(
                changed=False,
                pull_request_url=pull_request_url,
                head_repository=head_repository,
                base_repository=destination_repository,
                branch_name=branch_name,
                destination_path=destination_relative_path,
            )

        _run_command(
            ("git", "-C", str(clone_path), "commit", "--quiet", "-m", commit_message),
            env=env,
        )
        push_remote = "fork" if use_fork else "origin"
        _run_command(
            (
                "git",
                "-C",
                str(clone_path),
                "push",
                "--force-with-lease",
                "--set-upstream",
                push_remote,
                branch_name,
            ),
            env=env,
        )

        if pull_request_url is None:
            pull_request_url = _run_command(
                (
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    destination_repository,
                    "--base",
                    base_branch,
                    "--head",
                    head_selector,
                    "--title",
                    pull_request_title,
                    "--body",
                    pull_request_body,
                ),
                env=env,
            )

        return GitHubPublicationResult(
            changed=True,
            pull_request_url=pull_request_url,
            head_repository=head_repository,
            base_repository=destination_repository,
            branch_name=branch_name,
            destination_path=destination_relative_path,
        )
    finally:
        if clone_path.exists():
            shutil.rmtree(clone_path)


def _append_github_publication_output(result: GitHubPublicationResult) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    lines = (
        f"changed={str(result.changed).lower()}",
        f"pull_request_url={result.pull_request_url or ''}",
    )
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _append_chocolatey_output(result: ChocolateyPublicationResult) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    package_path = "" if result.package_path is None else str(result.package_path)
    lines = (
        f"already_published={str(result.already_published).lower()}",
        f"package_path={package_path}",
    )
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _resolve_winget_manifest_root(options: PublishWingetOptions) -> tuple[Path, Path, str]:
    paths = RepositoryPaths.discover(options.repository_root)
    manifest_root = _resolved_or_default(
        options.manifest_root,
        paths.artifact_root / "package-managers",
        base=paths.repository_root,
    )
    winget_manifest_root = manifest_root / "winget" / options.version
    if not winget_manifest_root.is_dir():
        msg = f"The winget manifest root '{winget_manifest_root}' was not found."
        raise FileNotFoundError(msg)

    working_root = _resolved_or_default(
        options.working_root,
        paths.artifact_root / "publication" / "winget",
        base=paths.repository_root,
    )
    tag = options.tag or f"v{options.version}"
    return winget_manifest_root, working_root, tag


def _resolve_scoop_manifest_path(options: PublishScoopOptions) -> tuple[Path, Path, str]:
    paths = RepositoryPaths.discover(options.repository_root)
    manifest_root = _resolved_or_default(
        options.manifest_root,
        paths.artifact_root / "package-managers",
        base=paths.repository_root,
    )
    scoop_manifest_path = manifest_root / "scoop" / options.package_file_name
    if not scoop_manifest_path.is_file():
        msg = f"The Scoop manifest '{scoop_manifest_path}' was not found."
        raise FileNotFoundError(msg)

    working_root = _resolved_or_default(
        options.working_root,
        paths.artifact_root / "publication" / "scoop",
        base=paths.repository_root,
    )
    tag = options.tag or f"v{options.version}"
    return scoop_manifest_path, working_root, tag


def _test_chocolatey_package_version_presence(
    feed_url: str,
    package_id: str,
    version: str,
    *,
    logger_name: str,
) -> bool:
    if not feed_url.strip():
        return False

    logger = get_logger(logger_name)
    normalized_feed_url = feed_url if feed_url.endswith("/") else f"{feed_url}/"
    filter_value = quote(f"Id eq '{package_id}' and Version eq '{version}'", safe="")
    request_uri = f"{normalized_feed_url}Packages()?$filter={filter_value}"

    try:
        response = httpx.get(
            request_uri,
            headers={"Accept": "application/atom+xml"},
            timeout=30.0,
        )
        response.raise_for_status()
        feed = ElementTree.fromstring(response.text)
        namespace = {"atom": _ATOM_XML_NAMESPACE}
        return bool(feed.findall(".//atom:entry", namespace))
    except (ElementTree.ParseError, OSError, httpx.HTTPError) as error:
        logger.warning(
            "Unable to query Chocolatey feed '%s' for %s %s. The publish step will continue. %s",
            feed_url,
            package_id,
            version,
            error,
        )
        return False


def _publish_chocolatey_package_to_source(
    package: Path,
    *,
    source: str,
    api_key: str,
    query_source: str,
    repository_root: Path,
) -> ChocolateyPublicationResult:
    if urlsplit(source).scheme not in {"http", "https"}:
        resolved_source_path = resolve_path(source, base=repository_root)
        if resolved_source_path is None:
            msg = "Unable to resolve the Chocolatey push source path."
            raise RuntimeError(msg)
        resolved_source_path.mkdir(parents=True, exist_ok=True)
        destination_path = resolved_source_path / package.name
        shutil.copy2(package, destination_path)
        return ChocolateyPublicationResult(
            already_published=False,
            package_path=destination_path,
            push_source=source,
            query_source=query_source,
        )

    with package.open("rb") as handle:
        response = httpx.post(
            source,
            headers={"X-NuGet-ApiKey": api_key},
            files={"package": (package.name, handle, "application/octet-stream")},
            timeout=httpx.Timeout(2700.0),
        )
    if response.status_code in (httpx.codes.CREATED, httpx.codes.ACCEPTED):
        return ChocolateyPublicationResult(
            already_published=False,
            package_path=package,
            push_source=source,
            query_source=query_source,
        )
    if response.status_code == httpx.codes.CONFLICT:
        return ChocolateyPublicationResult(
            already_published=True,
            package_path=package,
            push_source=source,
            query_source=query_source,
        )

    msg = (
        "Chocolatey push failed with status code "
        f"'{response.status_code} {response.reason_phrase}'. {response.text}"
    )
    raise RuntimeError(msg)


def run_publish_winget(
    options: PublishWingetOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    _ = runner
    logger = get_logger(_LOGGER_NAME)
    winget_manifest_root, working_root, tag = _resolve_winget_manifest_root(options)
    identifier_segments = options.package_identifier.split(".")
    if len(identifier_segments) < 2:
        msg = (
            f"The package identifier '{options.package_identifier}' must contain at least "
            "two segments."
        )
        raise ValueError(msg)

    destination_path = PurePosixPath("manifests", options.package_identifier[0].lower())
    for segment in identifier_segments:
        destination_path /= segment
    destination_path /= options.version
    sanitized_version = re.sub(r"[^A-Za-z0-9._-]", "-", options.version)
    release_url = f"https://github.com/{options.repository}/releases/tag/{tag}"
    pull_request_body = "\n".join(
        (
            f"Automated submission for {options.package_identifier} {options.version}.",
            "",
            f"- Source repository: {options.repository}",
            f"- Release tag: {tag}",
            f"- Release URL: {release_url}",
            "",
            "Generated from the published MSI by `.github\\workflows\\package-managers.yml`.",
        )
    )

    logger.info(
        "Prepare winget publication for %s in %s targeting %s.",
        options.package_identifier,
        winget_manifest_root,
        options.target_repository,
    )
    if not execute:
        logger.info("Dry run only; winget publication was not executed.")
        return 0

    result = _submit_github_pull_request(
        source_path=winget_manifest_root,
        destination_repository=options.target_repository,
        destination_path=destination_path.as_posix(),
        branch_name=f"automation/winget/{sanitized_version}",
        commit_message=f"Add {options.package_identifier} {options.version}",
        pull_request_title=f"Add {options.package_identifier} {options.version}",
        pull_request_body=pull_request_body,
        base_branch=options.base_branch,
        working_root=working_root,
    )
    _append_github_publication_output(result)
    logger.info("winget changed: %s", result.changed)
    logger.info("winget pull request: %s", result.pull_request_url or "<none>")
    return 0


def run_publish_scoop(
    options: PublishScoopOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    _ = runner
    logger = get_logger(_LOGGER_NAME)
    scoop_manifest_path, working_root, tag = _resolve_scoop_manifest_path(options)
    sanitized_version = re.sub(r"[^A-Za-z0-9._-]", "-", options.version)
    release_url = f"https://github.com/{options.repository}/releases/tag/{tag}"
    pull_request_body = "\n".join(
        (
            f"Automated Scoop manifest update for Squid4Win {options.version}.",
            "",
            f"- Source repository: {options.repository}",
            f"- Release tag: {tag}",
            f"- Release URL: {release_url}",
            "",
            (
                "Generated from the published portable zip by "
                "`.github\\workflows\\package-managers.yml`."
            ),
        )
    )

    logger.info(
        "Prepare Scoop publication from %s targeting %s.",
        scoop_manifest_path,
        options.target_repository,
    )
    if not execute:
        logger.info("Dry run only; Scoop publication was not executed.")
        return 0

    result = _submit_github_pull_request(
        source_path=scoop_manifest_path,
        destination_repository=options.target_repository,
        destination_path=PurePosixPath("bucket", options.package_file_name).as_posix(),
        branch_name=f"automation/scoop/{sanitized_version}",
        commit_message=f"Add squid4win {options.version}",
        pull_request_title=f"Add squid4win {options.version}",
        pull_request_body=pull_request_body,
        base_branch=options.base_branch,
        working_root=working_root,
    )
    _append_github_publication_output(result)
    logger.info("Scoop changed: %s", result.changed)
    logger.info("Scoop pull request: %s", result.pull_request_url or "<none>")
    return 0


def run_publish_chocolatey(
    options: PublishChocolateyOptions,
    runner: PlanRunner,
    *,
    execute: bool,
) -> int:
    _ = runner
    logger = get_logger(_LOGGER_NAME)
    paths = RepositoryPaths.discover(options.repository_root)
    repository_root = paths.repository_root
    package_root = _resolved_or_default(
        options.package_root,
        paths.artifact_root / "package-managers" / "chocolatey",
        base=repository_root,
    )
    output_root = _resolved_or_default(
        options.output_root,
        paths.artifact_root / "publication" / "chocolatey",
        base=repository_root,
    )
    nuspec_path = package_root / f"{options.package_id}.nuspec"
    if not nuspec_path.is_file():
        msg = f"The Chocolatey nuspec '{nuspec_path}' was not found."
        raise FileNotFoundError(msg)

    logger.info(
        "Prepare Chocolatey publication for %s from %s.",
        options.version,
        package_root,
    )
    logger.info("Push source: %s", options.push_source)
    logger.info("Query source: %s", options.query_source)
    if not execute:
        logger.info("Dry run only; Chocolatey publication was not executed.")
        return 0

    choco_api_key = os.getenv("CHOCO_API_KEY", "").strip()
    if not choco_api_key:
        msg = "CHOCO_API_KEY must be set before publishing Chocolatey packages."
        raise RuntimeError(msg)
    _require_command("choco")

    already_published = _test_chocolatey_package_version_presence(
        options.query_source,
        options.package_id,
        options.version,
        logger_name="squid4win.package_managers",
    )
    if already_published:
        result = ChocolateyPublicationResult(
            already_published=True,
            package_path=None,
            push_source=options.push_source,
            query_source=options.query_source,
        )
        _append_chocolatey_output(result)
        logger.info(
            "Chocolatey package %s %s is already published.",
            options.package_id,
            options.version,
        )
        return 0

    package_output_root = output_root / options.version
    package_output_root.mkdir(parents=True, exist_ok=True)
    _run_command(
        (
            "choco",
            "pack",
            str(nuspec_path),
            "--outputdirectory",
            str(package_output_root),
            "--limit-output",
        )
    )
    packages = sorted(
        (
            path
            for path in package_output_root.glob(f"{options.package_id}*.nupkg")
            if not path.name.endswith(".symbols.nupkg")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not packages:
        msg = f"Chocolatey pack did not produce a package in '{package_output_root}'."
        raise RuntimeError(msg)

    result = _publish_chocolatey_package_to_source(
        packages[0],
        source=options.push_source,
        api_key=choco_api_key,
        query_source=options.query_source,
        repository_root=repository_root,
    )
    _append_chocolatey_output(result)
    logger.info("Chocolatey already published: %s", result.already_published)
    logger.info("Chocolatey package path: %s", result.package_path or "<none>")
    return 0
