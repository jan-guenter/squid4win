from __future__ import annotations

import os
import shutil
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
from conan.tools.files import copy


class Squid4WinTrayConan(ConanFile):
    PROJECT_NAME = "Squid4Win.Tray"
    DIRECTORY_BUILD_PROPS_FILE = "Directory.Build.props"
    name = "squid4win_tray"
    version = "0.1"
    package_type = "application"
    settings = "os", "arch", "build_type"
    python_requires = "squid4win_recipe_base/1.0"
    python_requires_extend = "squid4win_recipe_base.Squid4WinRecipeBase"

    def export(self) -> None:
        repository_root = Path(self.recipe_folder).parents[2]
        project_root = repository_root / "src" / "tray" / self.PROJECT_NAME

        copy(
            self,
            self.DIRECTORY_BUILD_PROPS_FILE,
            src=os.fspath(repository_root),
            dst=os.path.join(self.export_folder, "build-support"),
        )
        copy(
            self,
            "LICENSE",
            src=os.fspath(repository_root),
            dst=os.path.join(self.export_folder, "build-support"),
        )
        copy(
            self,
            "*",
            src=os.fspath(project_root),
            dst=os.path.join(self.export_folder, "src", "tray", self.PROJECT_NAME),
            excludes=("bin/*", "obj/*"),
        )

    def layout(self) -> None:
        configuration_label = self._configuration_label()
        self.folders.source = "source"
        self.folders.build = os.path.join("build", configuration_label)
        self.folders.generators = os.path.join("build", configuration_label, "conan")

    def source(self) -> None:
        source_root = Path(self.source_folder)
        shutil.rmtree(source_root, ignore_errors=True)
        source_root.mkdir(parents=True, exist_ok=True)

        exported_project_root = Path(self.recipe_folder) / "src" / "tray" / self.PROJECT_NAME
        local_project_root = (
            Path(self.recipe_folder).parents[2]
            / "src"
            / "tray"
            / self.PROJECT_NAME
        )
        project_source_root = (
            exported_project_root
            if exported_project_root.is_dir()
            else local_project_root
        )
        if not project_source_root.is_dir():
            raise ConanException(
                f"Exported tray app source tree is missing at {project_source_root}."
            )

        self._copy_directory_contents(
            project_source_root, source_root / "src" / "tray" / self.PROJECT_NAME
        )
        exported_directory_build_props = (
            Path(self.recipe_folder) / "build-support" / self.DIRECTORY_BUILD_PROPS_FILE
        )
        local_directory_build_props = (
            Path(self.recipe_folder).parents[2] / self.DIRECTORY_BUILD_PROPS_FILE
        )
        shutil.copy2(
            (
                exported_directory_build_props
                if exported_directory_build_props.is_file()
                else local_directory_build_props
            ),
            source_root / self.DIRECTORY_BUILD_PROPS_FILE,
        )

    def validate(self) -> None:
        if str(self.settings.os) != "Windows":
            raise ConanInvalidConfiguration(
                "The tray app package only supports Windows."
            )

        if str(self.settings.arch) != "x86_64":
            raise ConanInvalidConfiguration(
                "The tray app package only supports x86_64."
            )

    def generate(self) -> None:
        VirtualBuildEnv(self).generate()
        VirtualRunEnv(self).generate()

    def build(self) -> None:
        project_path = (
            Path(self.source_folder)
            / "src"
            / "tray"
            / self.PROJECT_NAME
            / f"{self.PROJECT_NAME}.csproj"
        )
        publish_root = Path(self.build_folder) / "publish"

        shutil.rmtree(publish_root, ignore_errors=True)

        self.run(
            "dotnet publish "
            f'"{project_path}" '
            f"-c {self.settings.build_type} "
            f'-o "{publish_root}" '
            "--nologo "
            "-p:SelfContained=false "
            "-p:PublishSingleFile=false"
        )

        tray_executable = publish_root / f"{self.PROJECT_NAME}.exe"
        if not tray_executable.is_file():
            raise ConanException(
                f"Expected the published tray executable at {tray_executable}."
            )

    def package(self) -> None:
        publish_root = Path(self.build_folder) / "publish"
        exported_license_path = Path(self.recipe_folder) / "build-support" / "LICENSE"
        local_license_path = Path(self.recipe_folder).parents[2] / "LICENSE"
        copy(
            self,
            "*",
            src=os.fspath(publish_root),
            dst=os.path.join(self.package_folder, "bin"),
        )
        copy(
            self,
            "LICENSE",
            src=os.fspath(
                exported_license_path.parent
                if exported_license_path.is_file()
                else local_license_path.parent
            ),
            dst=os.path.join(self.package_folder, "licenses"),
        )

    def package_info(self) -> None:
        self.cpp_info.bindirs = ["bin"]
        self.runenv_info.prepend_path(
            "PATH", os.path.join(self.package_folder, "bin")
        )

