from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
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
        build_support_root = Path(self.export_folder) / "build-support"

        build_support_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            repository_root / self.DIRECTORY_BUILD_PROPS_FILE,
            build_support_root / self.DIRECTORY_BUILD_PROPS_FILE,
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
        self.folders.generators = self._generators_folder()
        self.cpp.build.bindirs = [os.path.join("editable-package", "bin")]
        self.cpp.build.includedirs = []
        self.cpp.build.libdirs = []

    def source(self) -> None:
        source_root = Path(self.source_folder)
        shutil.rmtree(source_root, ignore_errors=True)
        source_root.mkdir(parents=True, exist_ok=True)

        exported_project_root = Path(self.recipe_folder) / "src" / "tray" / self.PROJECT_NAME
        local_repository_root = self._local_repository_root()
        local_project_root = (
            local_repository_root / "src" / "tray" / self.PROJECT_NAME
            if local_repository_root is not None
            else None
        )
        project_source_root = (
            exported_project_root
            if exported_project_root.is_dir()
            else local_project_root
        )
        if project_source_root is None:
            raise ConanException(
                f"Exported tray app source tree is missing at {exported_project_root}, and no local repository root could be detected."
            )
        if not project_source_root.is_dir():
            raise ConanException(
                f"Tray app source tree is missing from both {exported_project_root} and {project_source_root}."
            )

        self._copy_directory_contents(
            project_source_root, source_root / "src" / "tray" / self.PROJECT_NAME
        )
        exported_directory_build_props = (
            Path(self.recipe_folder) / "build-support" / self.DIRECTORY_BUILD_PROPS_FILE
        )
        directory_build_props_path = exported_directory_build_props
        if not directory_build_props_path.is_file():
            if local_repository_root is None:
                raise ConanException(
                    f"Unable to locate {self.DIRECTORY_BUILD_PROPS_FILE} under {exported_directory_build_props}, and no local repository root could be detected."
                )
            directory_build_props_path = (
                local_repository_root / self.DIRECTORY_BUILD_PROPS_FILE
            )
        if not directory_build_props_path.is_file():
            raise ConanException(
                f"Unable to locate {self.DIRECTORY_BUILD_PROPS_FILE} for the tray recipe."
            )
        shutil.copy2(
            directory_build_props_path,
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

    def build(self) -> None:
        project_path = self._project_root() / f"{self.PROJECT_NAME}.csproj"
        publish_root = Path(self.build_folder) / "publish"
        editable_package_root = self._editable_package_root()

        shutil.rmtree(publish_root, ignore_errors=True)
        shutil.rmtree(editable_package_root, ignore_errors=True)

        publish_command = [
            "dotnet",
            "publish",
            os.fspath(project_path),
            "-c",
            str(self.settings.build_type),
            "-o",
            os.fspath(publish_root),
            "--nologo",
            "-p:SelfContained=false",
            "-p:PublishSingleFile=false",
        ]
        self.output.info(
            "RUN: " + subprocess.list2cmdline(publish_command)
        )
        result = subprocess.run(publish_command, check=False)
        if result.returncode != 0:
            raise ConanException(
                f"dotnet publish failed with exit code {result.returncode}."
            )

        tray_executable = publish_root / f"{self.PROJECT_NAME}.exe"
        if not tray_executable.is_file():
            raise ConanException(
                f"Expected the published tray executable at {tray_executable}."
            )

        self._materialize_package_root(publish_root, editable_package_root)

    def package(self) -> None:
        editable_package_root = self._editable_package_root()
        if not editable_package_root.is_dir():
            raise ConanException(
                f"Expected the tray editable package root at {editable_package_root}."
            )

        copy(
            self,
            "*",
            src=os.fspath(editable_package_root),
            dst=self.package_folder,
        )

    def package_info(self) -> None:
        self.cpp_info.bindirs = ["bin"]
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        if self.package_folder is not None:
            self.runenv_info.prepend_path(
                "PATH", os.path.join(self.package_folder, "bin")
            )

    def _project_root(self) -> Path:
        local_repository_root = self._local_repository_root()
        if local_repository_root is not None:
            project_root = local_repository_root / "src" / "tray" / self.PROJECT_NAME
            if project_root.is_dir():
                return project_root

        return Path(self.source_folder) / "src" / "tray" / self.PROJECT_NAME

    def _license_source_path(self) -> Path:
        exported_license_path = Path(self.recipe_folder) / "build-support" / "LICENSE"
        if exported_license_path.is_file():
            return exported_license_path

        local_repository_root = self._local_repository_root()
        if local_repository_root is not None:
            local_license_path = local_repository_root / "LICENSE"
            if local_license_path.is_file():
                return local_license_path

        raise ConanException(
            f"Unable to locate the tray app LICENSE file under {self.recipe_folder}."
        )

    def _editable_package_root(self) -> Path:
        return Path(self.build_folder) / "editable-package"

    def _local_repository_root(self) -> Path | None:
        for candidate_path in (self.build_folder, self.source_folder):
            if not candidate_path:
                continue

            candidate = Path(candidate_path).resolve()
            if any(part.lower() == ".conan2" for part in candidate.parts):
                continue

            for ancestor in (candidate, *candidate.parents):
                if (ancestor / ".git").exists():
                    return ancestor

        return None

    def _materialize_package_root(
        self, publish_root: Path, package_root: Path
    ) -> None:
        package_root.mkdir(parents=True, exist_ok=True)
        licenses_root = package_root / "licenses"
        licenses_root.mkdir(parents=True, exist_ok=True)
        copy(
            self,
            "*",
            src=os.fspath(publish_root),
            dst=os.path.join(os.fspath(package_root), "bin"),
        )
        shutil.copy2(self._license_source_path(), licenses_root / "LICENSE")
        third_party_packages = self._harvest_published_package_notices(
            publish_root, package_root
        )
        manifest_path = package_root / "licenses" / "third-party-package-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    "packages": third_party_packages,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _harvest_published_package_notices(
        self, publish_root: Path, package_root: Path
    ) -> list[dict[str, object]]:
        deps_path = publish_root / f"{self.PROJECT_NAME}.deps.json"
        if not deps_path.is_file():
            raise ConanException(
                f"Expected the published deps manifest at {deps_path}."
            )

        deps_data = json.loads(deps_path.read_text(encoding="utf-8"))
        runtime_target_name = (
            str(deps_data.get("runtimeTarget", {}).get("name", "")).strip()
        )
        runtime_target = dict(deps_data.get("targets", {}).get(runtime_target_name, {}))
        global_packages_root = self._nuget_global_packages_root()
        third_party_packages: list[dict[str, object]] = []
        for library_name, library_data in sorted(
            dict(deps_data.get("libraries", {})).items()
        ):
            if str(library_data.get("type", "")).strip().lower() != "package":
                continue

            target_entry = dict(runtime_target.get(library_name, {}))
            shipped_assets = self._deduplicate(
                [
                    str(asset_path).replace("\\", "/")
                    for asset_path in (
                        list(dict(target_entry.get("runtime", {})).keys())
                        + list(dict(target_entry.get("runtimeTargets", {})).keys())
                    )
                    if str(asset_path).strip()
                ]
            )
            if not shipped_assets:
                continue

            package_id, _, package_version = library_name.partition("/")
            if not package_id or not package_version:
                raise ConanException(
                    f"Unexpected NuGet library key '{library_name}' in {deps_path}."
                )

            package_path_value = str(library_data.get("path", "")).strip()
            if not package_path_value:
                raise ConanException(
                    f"The deps manifest did not declare a package path for '{library_name}'."
                )

            package_path = global_packages_root / Path(
                package_path_value.replace("/", os.sep)
            )
            if not package_path.is_dir():
                raise ConanException(
                    f"Expected the NuGet package cache directory for '{library_name}' at {package_path}."
                )

            package_metadata = self._read_nuget_package_metadata(package_path)
            notice_files = self._copy_nuget_notice_files(
                package_path, package_root, package_id
            )
            third_party_packages.append(
                {
                    "id": package_id,
                    "version": package_version,
                    "license": package_metadata.get("license", ""),
                    "project_url": package_metadata.get("project_url", ""),
                    "shipped_assets": shipped_assets,
                    "notice_files": notice_files,
                }
            )

        return third_party_packages

    def _nuget_global_packages_root(self) -> Path:
        configured_packages_root = os.getenv("NUGET_PACKAGES", "").strip()
        if configured_packages_root:
            packages_root = Path(configured_packages_root)
            if packages_root.is_dir():
                return packages_root

        result = subprocess.run(
            ["dotnet", "nuget", "locals", "global-packages", "--list"],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise ConanException(
                f"dotnet nuget locals failed with exit code {result.returncode}: {result.stderr.strip()}"
            )

        for output_line in (result.stdout or "").splitlines():
            if ":" not in output_line:
                continue

            label, _, value = output_line.partition(":")
            if label.strip().lower() != "global-packages":
                continue

            packages_root = Path(value.strip())
            if packages_root.is_dir():
                return packages_root

        raise ConanException(
            "Unable to resolve the NuGet global-packages cache location for tray dependency notice harvesting."
        )

    @staticmethod
    def _read_nuget_package_metadata(package_path: Path) -> dict[str, str]:
        nuspec_path = next(package_path.glob("*.nuspec"), None)
        if nuspec_path is None or not nuspec_path.is_file():
            return {}

        nuspec_text = nuspec_path.read_text(encoding="utf-8")

        def metadata_text(name: str) -> str:
            match = re.search(
                rf"<{name}\b[^>]*>(.*?)</{name}>",
                nuspec_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match is None:
                return ""
            return match.group(1).strip()

        return {
            "license": metadata_text("license") or metadata_text("licenseUrl"),
            "project_url": metadata_text("projectUrl"),
        }

    def _copy_nuget_notice_files(
        self, package_path: Path, package_root: Path, package_id: str
    ) -> list[str]:
        notice_candidates: list[Path] = []
        seen_paths: set[str] = set()
        for pattern in ("LICENSE*", "NOTICE*", "THIRD-PARTY-NOTICES*"):
            for candidate in sorted(package_path.glob(pattern)):
                if not candidate.is_file():
                    continue

                candidate_key = os.path.normcase(os.fspath(candidate))
                if candidate_key in seen_paths:
                    continue

                seen_paths.add(candidate_key)
                notice_candidates.append(candidate)

        if not notice_candidates:
            raise ConanException(
                f"Unable to locate license or notice files in the NuGet package cache for '{package_id}' at {package_path}."
            )

        destination_root = (
            package_root
            / "licenses"
            / "third-party"
            / "nuget"
            / package_id
        )
        destination_root.mkdir(parents=True, exist_ok=True)
        copied_notice_files: list[str] = []
        for source_path in notice_candidates:
            destination_path = destination_root / source_path.name
            shutil.copy2(source_path, destination_path)
            copied_notice_files.append(
                os.fspath(destination_path.relative_to(package_root)).replace(
                    "\\", "/"
                )
            )

        return copied_notice_files

    @staticmethod
    def _deduplicate(values: list[str]) -> list[str]:
        deduplicated_values: list[str] = []
        for value in values:
            if value not in deduplicated_values:
                deduplicated_values.append(value)

        return deduplicated_values
