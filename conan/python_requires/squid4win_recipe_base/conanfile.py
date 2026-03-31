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

    def _release_metadata(self) -> dict[str, object]:
        metadata_path = Path(self.recipe_folder) / "conan" / "squid-release.json"
        if not metadata_path.is_file():
            return {}

        return self._load_json_file("conan", "squid-release.json")

    def _build_settings(self) -> dict[str, object]:
        build_settings = self.conan_data.get("build")
        if not isinstance(build_settings, dict):
            raise ConanInvalidConfiguration(
                "conandata.yml must define a top-level 'build' mapping."
            )

        return build_settings

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

    def _generators_folder(self) -> str:
        return os.path.join("build", self._configuration_label(), "conan")

    def _build_setting(self, key: str, default: object | None = None) -> object:
        return self._build_settings().get(key, default)

    def _profile_name(self) -> str:
        return str(
            self._build_setting("profile_name", "msys2-mingw-x64")
        ).strip() or "msys2-mingw-x64"

    def _stage_root_template(self) -> str:
        stage_root = str(
            self._build_setting("stage_root", r"build\install\{configuration}")
        ).strip()
        return stage_root or r"build\install\{configuration}"

    def _service_name(self) -> str:
        service_name = str(self._build_setting("service_name", "Squid4Win")).strip()
        return service_name or "Squid4Win"

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

        stage_root = self._stage_root_template().replace(
            "{configuration}", self._configuration_label()
        )
        return (worktree_root / stage_root).resolve()


class Squid4WinRecipeBasePackage(ConanFile):
    name = "squid4win_recipe_base"
    version = "1.0"
    package_type = "python-require"

