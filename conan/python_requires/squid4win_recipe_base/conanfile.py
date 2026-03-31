from __future__ import annotations

from collections.abc import Iterable
import json
import os
import shutil
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import load


class Squid4WinRecipeBase:
    def _load_json_file(self, *relative_parts: str) -> dict[str, object]:
        json_path = Path(self.recipe_folder).joinpath(*relative_parts)
        return json.loads(load(self, os.fspath(json_path)))

    def _build_profile(self) -> dict[str, object]:
        return self._load_json_file("config", "build-profile.json")

    def _release_metadata(self) -> dict[str, object]:
        metadata_path = Path(self.recipe_folder) / "conan" / "squid-release.json"
        if not metadata_path.is_file():
            return {}

        return self._load_json_file("conan", "squid-release.json")

    @staticmethod
    def _string_list(values: object) -> list[str]:
        if values is None:
            return []

        raw_values: Iterable[object]
        if isinstance(values, str):
            raw_values = [values]
        elif isinstance(values, dict):
            raw_values = values.values()
        elif isinstance(values, Iterable):
            raw_values = values
        else:
            raw_values = [values]

        normalized_values: list[str] = []
        for value in raw_values:
            text = str(value).strip()
            if text:
                normalized_values.append(text)

        return normalized_values

    def _configuration_label(self) -> str:
        return str(self.settings.build_type).lower()

    def _validate_native_windows(self) -> None:
        if str(self.settings.os) != "Windows":
            raise ConanInvalidConfiguration(
                "The squid4win recipes only support native Windows builds."
            )

        if str(self.settings.arch) != "x86_64":
            raise ConanInvalidConfiguration("Only x86_64 builds are supported.")

        compiler = getattr(self.settings, "compiler", None)
        if compiler is not None and str(compiler) != "gcc":
            raise ConanInvalidConfiguration(
                "Use the generated MSYS2 MinGW-w64 GCC host profile."
            )

    @staticmethod
    def _to_msys_path(path: os.PathLike[str] | str) -> str:
        normalized_path = os.path.abspath(os.fspath(path)).replace("\\", "/")
        if len(normalized_path) >= 2 and normalized_path[1] == ":":
            return f"/{normalized_path[0].lower()}{normalized_path[2:]}"

        return normalized_path

    @staticmethod
    def _copy_directory_contents(
        source: os.PathLike[str] | str, destination: os.PathLike[str] | str
    ) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.mkdir(parents=True, exist_ok=True)

        for item in source_path.iterdir():
            target = destination_path / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    def _local_worktree_root(self) -> Path | None:
        candidate = Path(self.recipe_folder)
        if (candidate / ".git").exists():
            return candidate

        return None

    def _local_stage_root(self) -> Path | None:
        worktree_root = self._local_worktree_root()
        if worktree_root is None:
            return None

        stage_root = str(self._build_profile().get("stageRoot", "build\\install\\release"))
        return (worktree_root / stage_root).resolve()


class Squid4WinRecipeBasePackage(ConanFile):
    name = "squid4win_recipe_base"
    version = "1.0"
    package_type = "python-require"

