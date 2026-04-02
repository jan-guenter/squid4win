from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Final

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, TypeAdapter

_USER_AGENT: Final[str] = "squid4win-automation"


class GitHubReleaseAsset(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    browser_download_url: AnyHttpUrl
    digest: str | None = None


class GitHubRelease(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tag_name: str
    name: str | None = None
    draft: bool = False
    prerelease: bool = False
    published_at: datetime | None = None
    html_url: AnyHttpUrl | None = None
    assets: tuple[GitHubReleaseAsset, ...] = ()

    @property
    def version(self) -> str:
        return self.tag_name.removeprefix("SQUID_").replace("_", ".")


class ResolvedUpstreamRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    version: str
    tag: str
    published_at: datetime | None = None
    source_archive: AnyHttpUrl
    source_signature: AnyHttpUrl | None = None
    source_archive_sha256: str | None = None
    html_url: AnyHttpUrl | None = None

    @property
    def published_at_text(self) -> str | None:
        if self.published_at is None:
            return None

        moment = self.published_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_RELEASE_LIST_ADAPTER: Final[TypeAdapter[list[GitHubRelease]]] = TypeAdapter(list[GitHubRelease])


class GitHubReleaseClient:
    def __init__(self, token: str | None = None) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        }
        if token or os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token or os.getenv('GITHUB_TOKEN')}"

        self._client = httpx.Client(
            base_url="https://api.github.com",
            follow_redirects=True,
            headers=headers,
            timeout=30.0,
        )

    def __enter__(self) -> GitHubReleaseClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def list_releases(self, repository: str, *, per_page: int = 20) -> list[GitHubRelease]:
        response = self._client.get(f"/repos/{repository}/releases", params={"per_page": per_page})
        response.raise_for_status()
        return _RELEASE_LIST_ADAPTER.validate_python(response.json())

    def resolve_release(
        self,
        repository: str,
        *,
        major_version: int | None = None,
        include_prerelease: bool = False,
    ) -> ResolvedUpstreamRelease:
        for release in self.list_releases(repository):
            if release.draft:
                continue
            if release.prerelease and not include_prerelease:
                continue
            if major_version is not None and int(release.version.split(".", 1)[0]) != major_version:
                continue

            source_archive = self._find_asset(release, f"squid-{release.version}.tar.xz")
            if source_archive is None:
                msg = f"Release {release.tag_name} does not contain squid-{release.version}.tar.xz."
                raise LookupError(msg)
            source_signature = self._find_asset(release, f"squid-{release.version}.tar.xz.asc")
            source_archive_sha256 = self._extract_sha256(source_archive.digest)
            if source_archive_sha256 is None:
                msg = (
                    f"Release {release.tag_name} does not expose a SHA256 digest "
                    f"for squid-{release.version}.tar.xz."
                )
                raise LookupError(msg)

            return ResolvedUpstreamRelease(
                repository=repository,
                version=release.version,
                tag=release.tag_name,
                published_at=release.published_at,
                source_archive=source_archive.browser_download_url,
                source_signature=(
                    source_signature.browser_download_url if source_signature else None
                ),
                source_archive_sha256=source_archive_sha256,
                html_url=release.html_url,
            )

        msg = f"No matching release was found for {repository}."
        raise LookupError(msg)

    @staticmethod
    def _find_asset(release: GitHubRelease, name: str) -> GitHubReleaseAsset | None:
        return next((asset for asset in release.assets if asset.name == name), None)

    @staticmethod
    def _extract_sha256(digest: str | None) -> str | None:
        if digest is None:
            return None

        match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest)
        return match.group(1).lower() if match else None
