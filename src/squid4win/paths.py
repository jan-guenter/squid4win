from __future__ import annotations

import os
from pathlib import Path
from typing import Final

_REPOSITORY_MARKERS: Final[tuple[str, ...]] = ("README.md", "AGENTS.md", "conanfile.py", "scripts")


def _looks_like_repository_root(candidate: Path) -> bool:
    return all((candidate / marker).exists() for marker in _REPOSITORY_MARKERS)


def _candidate_starts(explicit: Path | None = None) -> list[Path]:
    candidates: list[Path] = []

    if explicit is not None:
        candidates.append(explicit)

    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        candidates.append(Path(workspace))

    candidates.extend((Path.cwd(), Path(__file__).resolve()))
    return candidates


def discover_repository_root(start: Path | None = None) -> Path:
    for candidate in _candidate_starts(start):
        current = candidate.resolve()
        if current.is_file():
            current = current.parent

        for parent in (current, *current.parents):
            if _looks_like_repository_root(parent):
                return parent

    msg = "Unable to locate the squid4win repository root from the current environment."
    raise FileNotFoundError(msg)


def resolve_path(value: str | Path | None, *, base: Path) -> Path | None:
    if value is None:
        return None

    path = Path(value)
    if not path.is_absolute():
        path = base / path

    return path.resolve()
