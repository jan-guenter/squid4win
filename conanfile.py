from __future__ import annotations

import json
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.env import Environment, VirtualBuildEnv, VirtualRunEnv
from conan.tools.files import load
from conan.tools.gnu import AutotoolsToolchain
from conan.tools.layout import basic_layout


class Squid4WinBuildConan(ConanFile):
    name = "squid4win-build"
    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"
    exports = "conan/squid-release.json", "config/build-profile.json"
    no_copy_source = True
    win_bash = True

    def set_version(self) -> None:
        self.version = self._metadata()["version"]

    def layout(self) -> None:
        basic_layout(self, src_folder=".")

    def validate(self) -> None:
        if str(self.settings.os) != "Windows":
            raise ConanInvalidConfiguration(
                "This recipe only scaffolds native Windows/MSYS2 builds."
            )
        if str(self.settings.arch) != "x86_64":
            raise ConanInvalidConfiguration("Only x86_64 builds are scaffolded today.")
        if str(self.settings.compiler) != "gcc":
            raise ConanInvalidConfiguration(
                "Use the MSYS2 MinGW-w64 GCC profile in conan\\profiles\\msys2-mingw-x64."
            )

    def requirements(self) -> None:
        for reference in self._string_list(
            self._build_profile().get("conanRequirements", [])
        ):
            self.requires(reference)

    def build_requirements(self) -> None:
        for reference in self._string_list(
            self._build_profile().get("conanToolRequirements", [])
        ):
            self.tool_requires(reference)

    def generate(self) -> None:
        metadata = self._metadata()
        build_profile = self._build_profile()
        conan_requirements = self._string_list(
            build_profile.get("conanRequirements", [])
        )
        conan_tool_requirements = self._string_list(
            build_profile.get("conanToolRequirements", [])
        )

        build_env = VirtualBuildEnv(self)
        build_env.generate()

        run_env = VirtualRunEnv(self)
        run_env.generate()

        release_env = Environment()
        release_env.define("SQUID_VERSION", metadata["version"])
        release_env.define("SQUID_TAG", metadata["tag"])
        release_env.define("SQUID_SOURCE_ARCHIVE", metadata["assets"]["source_archive"])
        release_env.define(
            "SQUID_CONAN_REQUIREMENTS", ";".join(conan_requirements)
        )
        release_env.define(
            "SQUID_CONAN_TOOL_REQUIREMENTS", ";".join(conan_tool_requirements)
        )
        release_env.vars(self, scope="build").save_script("squid-release")

        toolchain = AutotoolsToolchain(self)
        toolchain.generate()

    def _metadata(self) -> dict[str, object]:
        metadata_path = Path(self.recipe_folder) / "conan" / "squid-release.json"
        return json.loads(load(self, str(metadata_path)))

    def _build_profile(self) -> dict[str, object]:
        build_profile_path = Path(self.recipe_folder) / "config" / "build-profile.json"
        return json.loads(load(self, str(build_profile_path)))

    @staticmethod
    def _string_list(values: object) -> list[str]:
        if values is None:
            return []

        normalized_values: list[str] = []
        for value in values:
            text = str(value).strip()
            if text:
                normalized_values.append(text)

        return normalized_values
