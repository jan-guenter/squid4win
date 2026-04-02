from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from typing import Final

from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from squid4win.logging_utils import get_logger
from squid4win.models import RepositoryPaths, UpstreamVersionOptions
from squid4win.paths import resolve_path
from squid4win.upstream import ResolvedUpstreamRelease
from squid4win.utils.actions import set_outputs

_DEFAULT_NEWLINE: Final[str] = "\n"
_DEFAULT_TRACK: Final[str] = "stable"
_REPOSITORY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?P<owner>[^/]+)/(?P<repo>[^/]+)$")
_PATCH_SECTION_PATTERN: Final[re.Pattern[str]] = re.compile(r'patches:\r?\n\s+"[^"]+":')
_BUILD_SECTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?ms)^build:\r?\n.*$")
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


def expected_squid_tag(version: str) -> str:
    return f"SQUID_{version.replace('.', '_')}"


def _resolved_or_default(value: Path | None, default: Path, *, base: Path) -> Path:
    return resolve_path(value, base=base) or default


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _read_text_if_exists(path: Path) -> str | None:
    return _read_text(path) if path.exists() else None


def _detect_newline(text: str | None) -> str:
    if text is not None and "\r\n" in text:
        return "\r\n"
    return _DEFAULT_NEWLINE


def _parse_published_at(value: str | None) -> datetime | None:
    if value is None:
        return None

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _render_json(model: BaseModel, *, newline: str) -> str:
    rendered = model.model_dump_json(by_alias=True, indent=2)
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    return rendered.replace("\n", newline)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_bytes(content.encode("utf-8"))
    temporary_path.replace(path)


@dataclass(frozen=True)
class PlannedFileUpdate:
    path: Path
    content: str
    changed: bool


@dataclass(frozen=True)
class VersionSyncPlan:
    release: TargetUpstreamRelease
    metadata: PlannedFileUpdate
    config: PlannedFileUpdate
    conan_data: PlannedFileUpdate

    @property
    def changed(self) -> bool:
        return self.metadata.changed or self.config.changed or self.conan_data.changed

    @property
    def changed_paths(self) -> tuple[Path, ...]:
        return tuple(
            update.path
            for update in (self.metadata, self.config, self.conan_data)
            if update.changed
        )


class TargetUpstreamRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    version: str
    tag: str
    published_at: datetime | None = None
    source_archive: AnyHttpUrl
    source_signature: AnyHttpUrl | None = None
    source_archive_sha256: str

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if _REPOSITORY_PATTERN.fullmatch(value) is None:
            msg = "Repository values must follow the owner/name format."
            raise ValueError(msg)
        return value

    @field_validator("source_archive_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if _SHA256_PATTERN.fullmatch(normalized) is None:
            msg = "Source archive digests must be 64-character SHA256 values."
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def validate_tag_matches_version(self) -> TargetUpstreamRelease:
        expected_tag = expected_squid_tag(self.version)
        if self.tag != expected_tag:
            msg = f"Upstream tags must match version {self.version} using {expected_tag}."
            raise ValueError(msg)
        return self

    @property
    def published_at_text(self) -> str | None:
        if self.published_at is None:
            return None

        moment = self.published_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def owner(self) -> str:
        match = _REPOSITORY_PATTERN.fullmatch(self.repository)
        assert match is not None  # validated in validate_repository
        return match.group("owner")

    @property
    def repo(self) -> str:
        match = _REPOSITORY_PATTERN.fullmatch(self.repository)
        assert match is not None  # validated in validate_repository
        return match.group("repo")

    @classmethod
    def from_options(cls, options: UpstreamVersionOptions) -> TargetUpstreamRelease:
        if (
            options.version is None
            or options.tag is None
            or options.source_archive is None
            or options.source_archive_sha256 is None
        ):
            msg = (
                "Manual upstream version updates require explicit values for version, tag, "
                "source_archive, and source_archive_sha256."
            )
            raise ValueError(msg)

        return cls(
            repository=options.repository,
            version=options.version,
            tag=options.tag,
            published_at=_parse_published_at(options.published_at),
            source_archive=options.source_archive,
            source_signature=options.source_signature,
            source_archive_sha256=options.source_archive_sha256,
        )

    @classmethod
    def from_resolved_release(
        cls,
        resolved_release: ResolvedUpstreamRelease,
    ) -> TargetUpstreamRelease:
        if resolved_release.source_archive_sha256 is None:
            msg = (
                f"Release {resolved_release.tag} does not expose a SHA256 digest "
                f"for squid-{resolved_release.version}.tar.xz."
            )
            raise ValueError(msg)

        return cls(
            repository=resolved_release.repository,
            version=resolved_release.version,
            tag=resolved_release.tag,
            published_at=resolved_release.published_at,
            source_archive=resolved_release.source_archive,
            source_signature=resolved_release.source_signature,
            source_archive_sha256=resolved_release.source_archive_sha256,
        )


class SquidReleaseAssets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_archive: AnyHttpUrl
    source_signature: AnyHttpUrl | None = None
    source_archive_sha256: str


class SquidReleaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    version: str
    tag: str
    published_at: str | None = None
    assets: SquidReleaseAssets


class SquidVersionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    owner: str
    repo: str
    track: str = _DEFAULT_TRACK
    version: str
    tag: str
    source_archive_url: AnyHttpUrl = Field(
        validation_alias=AliasChoices("sourceArchiveUrl", "source_archive_url"),
        serialization_alias="sourceArchiveUrl",
    )


class VersionSyncResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    changed: bool
    repository: str
    version: str
    tag: str
    metadata_path: Path
    config_path: Path
    conan_data_path: Path
    planned_paths: tuple[Path, ...] = ()


class UpstreamVersionManager:
    def __init__(
        self,
        options: UpstreamVersionOptions,
        *,
        logger: Logger | None = None,
    ) -> None:
        paths = RepositoryPaths.discover(options.repository_root)
        self._repository_root = paths.repository_root
        self._metadata_path = _resolved_or_default(
            options.metadata_path,
            paths.squid_release_metadata_path,
            base=paths.repository_root,
        )
        self._config_path = _resolved_or_default(
            options.config_path,
            paths.squid_version_config_path,
            base=paths.repository_root,
        )
        self._conan_data_path = _resolved_or_default(
            options.conan_data_path,
            paths.conan_data_path,
            base=paths.repository_root,
        )
        self._logger = logger or get_logger("squid4win.upstream")

    def synchronize(
        self,
        release: TargetUpstreamRelease,
        *,
        execute: bool,
    ) -> VersionSyncResult:
        plan = self.build_plan(release)
        self._describe(plan, execute=execute)

        changed = False
        if execute and plan.changed:
            for update in (plan.metadata, plan.config, plan.conan_data):
                if update.changed:
                    _write_text(update.path, update.content)
            changed = True
            self._logger.info(
                "Synchronized Squid version metadata to %s (%s).",
                release.version,
                release.tag,
            )
        elif execute:
            self._logger.info(
                "Squid version metadata already matches %s (%s).",
                release.version,
                release.tag,
            )
        else:
            self._logger.info(
                "Dry-run only. Re-run with --execute to write the updated metadata files."
            )

        result = VersionSyncResult(
            changed=changed,
            repository=release.repository,
            version=release.version,
            tag=release.tag,
            metadata_path=self._metadata_path,
            config_path=self._config_path,
            conan_data_path=self._conan_data_path,
            planned_paths=plan.changed_paths,
        )
        set_outputs(
            {
                "changed": result.changed,
                "version": result.version,
                "tag": result.tag,
            }
        )
        return result

    def build_plan(self, release: TargetUpstreamRelease) -> VersionSyncPlan:
        metadata_existing = _read_text_if_exists(self._metadata_path)
        metadata_newline = _detect_newline(metadata_existing)
        metadata_content = _render_json(
            SquidReleaseMetadata(
                repository=release.repository,
                version=release.version,
                tag=release.tag,
                published_at=release.published_at_text,
                assets=SquidReleaseAssets(
                    source_archive=release.source_archive,
                    source_signature=release.source_signature,
                    source_archive_sha256=release.source_archive_sha256,
                ),
            ),
            newline=metadata_newline,
        )

        config_existing = _read_text_if_exists(self._config_path)
        config_track = self._load_existing_track(config_existing)
        config_newline = _detect_newline(config_existing)
        config_content = _render_json(
            SquidVersionConfig(
                owner=release.owner,
                repo=release.repo,
                track=config_track,
                version=release.version,
                tag=release.tag,
                source_archive_url=release.source_archive,
            ),
            newline=config_newline,
        )

        conan_existing = _read_text_if_exists(self._conan_data_path)
        if conan_existing is None:
            msg = (
                f"Expected existing conandata.yml at {self._conan_data_path} so the Squid version "
                "update can preserve the current build metadata."
            )
            raise FileNotFoundError(msg)
        conan_content = self._render_conan_data(conan_existing, release)

        return VersionSyncPlan(
            release=release,
            metadata=PlannedFileUpdate(
                path=self._metadata_path,
                content=metadata_content,
                changed=metadata_existing != metadata_content,
            ),
            config=PlannedFileUpdate(
                path=self._config_path,
                content=config_content,
                changed=config_existing != config_content,
            ),
            conan_data=PlannedFileUpdate(
                path=self._conan_data_path,
                content=conan_content,
                changed=conan_existing != conan_content,
            ),
        )

    def _describe(self, plan: VersionSyncPlan, *, execute: bool) -> None:
        if not plan.changed:
            self._logger.info(
                "All tracked Squid version files already match %s (%s).",
                plan.release.version,
                plan.release.tag,
            )
            return

        action = "Updating" if execute else "Would update"
        self._logger.info(
            "%s Squid version metadata to %s (%s).",
            action,
            plan.release.version,
            plan.release.tag,
        )
        for path in plan.changed_paths:
            self._logger.info("  %s", self._display_path(path))

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._repository_root))
        except ValueError:
            return str(path)

    def _load_existing_track(self, existing_content: str | None) -> str:
        if existing_content is None:
            return _DEFAULT_TRACK
        return SquidVersionConfig.model_validate_json(existing_content).track

    def _render_conan_data(self, existing_content: str, release: TargetUpstreamRelease) -> str:
        build_and_patch_section_match = _BUILD_SECTION_PATTERN.search(existing_content)
        if build_and_patch_section_match is None:
            msg = f"Unable to locate the top-level build section in {self._conan_data_path}."
            raise ValueError(msg)

        build_and_patch_section = build_and_patch_section_match.group(0)
        if _PATCH_SECTION_PATTERN.search(build_and_patch_section) is None:
            msg = f"Unable to locate the versioned patches section in {self._conan_data_path}."
            raise ValueError(msg)

        newline = _detect_newline(existing_content)
        new_patch_header = f'patches:{newline}  "{release.version}":'
        preserved_tail = _PATCH_SECTION_PATTERN.sub(
            new_patch_header,
            build_and_patch_section,
            count=1,
        )
        lines = (
            "sources:",
            f'  "{release.version}":',
            f'    url: "{release.source_archive}"',
            f'    sha256: "{release.source_archive_sha256}"',
            "    strip_root: true",
            "",
        )
        rendered = newline.join(lines) + newline + preserved_tail
        if not rendered.endswith(newline):
            rendered = f"{rendered}{newline}"
        return rendered
