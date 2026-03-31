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
from conan.tools.env import Environment, VirtualBuildEnv, VirtualRunEnv
from conan.tools.files import (
    apply_conandata_patches,
    copy,
    export_conandata_patches,
    get,
    load,
    mkdir,
    save,
)
from conan.tools.gnu import AutotoolsToolchain

MACRO_NAME_PATTERN = re.compile(r"[A-Za-z_]\w*\Z", re.ASCII)


class Squid4WinConan(ConanFile):
    name = "squid4win"
    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"
    no_copy_source = True
    python_requires = "squid4win_recipe_base/1.0"
    python_requires_extend = "squid4win_recipe_base.Squid4WinRecipeBase"
    options = {
        "with_tray": [True, False],
        "with_runtime_dlls": [True, False],
        "with_packaging_support": [True, False],
    }
    default_options = {
        "with_tray": False,
        "with_runtime_dlls": False,
        "with_packaging_support": False,
    }

    def set_version(self) -> None:
        metadata = self._release_metadata()
        self.version = str(metadata["version"])

    def export(self) -> None:
        export_conandata_patches(self)
        copy(
            self,
            "squid-release.json",
            src=os.path.join(self.recipe_folder, "conan"),
            dst=os.path.join(self.export_folder, "conan"),
        )
        copy(
            self,
            "LICENSE",
            src=self.recipe_folder,
            dst=os.path.join(self.export_folder, "licenses"),
        )
        copy(
            self,
            "*",
            src=os.path.join(self.recipe_folder, "packaging", "defaults"),
            dst=os.path.join(self.export_folder, "packaging", "defaults"),
        )
        copy(
            self,
            "Manage-SquidService.ps1",
            src=os.path.join(self.recipe_folder, "scripts", "installer"),
            dst=os.path.join(self.export_folder, "scripts", "installer"),
        )

    def layout(self) -> None:
        configuration_label = self._configuration_label()
        self.folders.source = os.path.join("sources", f"squid-{self.version}")
        self.folders.build = os.path.join("build", configuration_label)
        self.folders.generators = self._generators_folder()

    def validate(self) -> None:
        self._validate_native_windows()
        if self._option_enabled("with_runtime_dlls") and not self._option_enabled(
            "with_packaging_support"
        ):
            raise ConanInvalidConfiguration(
                "with_runtime_dlls=True requires with_packaging_support=True so "
                "the bundled notices and source manifest stay in sync."
            )

    def requirements(self) -> None:
        if self._option_enabled("with_tray"):
            self.requires("squid4win_tray/0.1")

    def build_requirements(self) -> None:
        for reference in self._string_list(
            self._build_settings().get("tool_requires", [])
        ):
            self.tool_requires(reference)

    def generate(self) -> None:
        metadata = self._release_metadata()
        build_settings = self._build_settings()

        VirtualBuildEnv(self).generate()
        VirtualRunEnv(self).generate()

        release_env = Environment()
        release_env.define("SQUID_VERSION", str(metadata["version"]))
        release_env.define("SQUID_TAG", str(metadata["tag"]))
        release_env.define(
            "SQUID_SOURCE_ARCHIVE", str(metadata["assets"]["source_archive"])
        )
        release_env.define(
            "SQUID_CONAN_TOOL_REQUIREMENTS",
            ";".join(self._string_list(build_settings.get("tool_requires", []))),
        )
        release_env.vars(self, scope="build").save_script("squid-release")

        AutotoolsToolchain(self).generate()

    def source(self) -> None:
        source_data = dict(self.conan_data["sources"][str(self.version)])
        strip_root = bool(source_data.pop("strip_root", True))
        source_root = Path(self.source_folder)
        source_ready_marker = source_root / ".squid4win-source-ready"

        if source_ready_marker.is_file():
            self.output.info(f"Reusing existing source tree at {source_root}.")
            return

        mkdir(self, self.source_folder)
        for child in source_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        get(self, destination=self.source_folder, strip_root=strip_root, **source_data)
        apply_conandata_patches(self)
        source_ready_marker.write_text("patched\n", encoding="ascii")

    def build(self) -> None:
        metadata = self._release_metadata()
        build_settings = self._build_settings()
        source_root = Path(self.source_folder)
        build_root = Path(self.build_folder)
        bundle_root = build_root / "bundle"
        config_site_path = build_root / "config.site"
        bootstrap_marker_path = build_root / "squid4win-bootstrap-ran"
        generated_header_path = build_root / "include" / "autoconf.h"
        confdefs_copy_path = build_root / "squid4win-confdefs.h"
        config_log_path = build_root / "config.log"
        configuration_label = self._configuration_label()
        msys2_settings = dict(build_settings.get("msys2", {}))
        msys2_env_directory = str(msys2_settings.get("env", "mingw64")).lower()
        msys2_env_name = str(msys2_settings.get("env", "mingw64")).upper()
        msys2_prefix_path = f"/{msys2_env_directory}"
        pkg_config_binary_path = f"/{msys2_env_directory}/bin/pkg-config"
        pkg_config_lib_dir = (
            f"/{msys2_env_directory}/lib/pkgconfig:/{msys2_env_directory}/share/pkgconfig"
        )
        build_env_script = Path(self.generators_folder) / "conanbuild.sh"
        autotools_script = Path(self.generators_folder) / "conanautotoolstoolchain.sh"
        release_script = Path(self.generators_folder) / "squid-release.sh"

        shutil.rmtree(bundle_root, ignore_errors=True)
        bootstrap_marker_path.unlink(missing_ok=True)
        build_root.mkdir(parents=True, exist_ok=True)

        configure_cache_lines = self._configure_cache_lines(build_settings)
        if configure_cache_lines:
            save(
                self,
                os.fspath(config_site_path),
                "\n".join(configure_cache_lines) + "\n",
                encoding="ascii",
            )

        configure_arguments = self._deduplicate(
            [
                f"--prefix={self._to_msys_path(bundle_root)}",
                f"--build={str(build_settings['host_triplet'])}",
                f"--host={str(build_settings['host_triplet'])}",
                *self._string_list(build_settings.get("configure_args", [])),
                *self._additional_configure_args(),
            ]
        )
        configure_argument_text = " ".join(
            self._bash_quote(argument) for argument in configure_arguments
        )
        source_root_msys = self._to_msys_path(source_root)
        build_root_msys = self._to_msys_path(build_root)
        bootstrap_marker_path_msys = self._to_msys_path(bootstrap_marker_path)
        mingw_package_root = self._dependency_package_root("mingw-builds")
        if mingw_package_root is None:
            raise ConanException(
                "The mingw-builds tool requirement is not available to the root recipe."
            )

        mingw_bin_root = mingw_package_root / "bin"
        mingw_bin_root_msys = self._to_msys_path(mingw_bin_root)
        mingw_tool_paths = {
            "CC": mingw_bin_root / "gcc.exe",
            "CXX": mingw_bin_root / "g++.exe",
            "AR": mingw_bin_root / "ar.exe",
            "AS": mingw_bin_root / "as.exe",
            "LD": mingw_bin_root / "ld.exe",
            "NM": mingw_bin_root / "nm.exe",
            "RANLIB": mingw_bin_root / "ranlib.exe",
            "STRIP": mingw_bin_root / "strip.exe",
            "STRINGS": mingw_bin_root / "strings.exe",
            "OBJDUMP": mingw_bin_root / "objdump.exe",
            "GCOV": mingw_bin_root / "gcov.exe",
        }

        bash_common_lines = [
            f"export MSYSTEM={msys2_env_name}",
            "export CHERE_INVOKING=1",
            "set -o pipefail",
        ]

        for generated_script in (build_env_script, autotools_script, release_script):
            if generated_script.is_file():
                bash_common_lines.append(
                    f"source {self._bash_quote(self._to_msys_path(generated_script))}"
                )

        bash_common_lines.extend(
            (
                "source /etc/profile",
                (
                    f'export PATH="{mingw_bin_root_msys}:/{msys2_env_directory}/bin:$MSYS_BIN:/usr/bin:/usr/bin/core_perl:$PATH"'
                ),
                f'export CPPFLAGS="-I{msys2_prefix_path}/include $CPPFLAGS"',
                f'export LDFLAGS="-L{msys2_prefix_path}/lib $LDFLAGS"',
            )
        )
        bash_common_lines.extend(
            f"export {tool_name}={self._bash_quote(self._to_msys_path(tool_path))}"
            for tool_name, tool_path in mingw_tool_paths.items()
        )
        bash_common_lines.append(
            f"export PKG_CONFIG={self._bash_quote(pkg_config_binary_path)}"
        )
        bash_common_lines.append(
            f"export PKG_CONFIG_LIBDIR={self._bash_quote(pkg_config_lib_dir)}"
        )

        if config_site_path.is_file():
            bash_common_lines.append(
                f"export CONFIG_SITE={self._bash_quote(self._to_msys_path(config_site_path))}"
            )

        configure_lines = list(bash_common_lines)
        configure_lines.extend(
            (
                f"mkdir -p {self._bash_quote(build_root_msys)}",
                f"rm -f {self._bash_quote(bootstrap_marker_path_msys)}",
                f"cd {self._bash_quote(source_root_msys)}",
                (
                    "if [ -f ./bootstrap.sh ] && "
                    "{ [ ! -x ./configure ] || [ ! -f ./Makefile.in ] "
                    "|| [ ! -f ./src/Makefile.in ] || [ ! -f ./libltdl/Makefile.in ] "
                    "|| [ ! -f ./cfgaux/ltmain.sh ] || [ ! -f ./cfgaux/compile ] "
                    "|| [ ! -f ./cfgaux/config.guess ] || [ ! -f ./cfgaux/config.sub ] "
                    "|| [ ! -f ./cfgaux/missing ] || [ ! -f ./cfgaux/install-sh ]; }; "
                    f"then ./bootstrap.sh || exit $?; touch {self._bash_quote(bootstrap_marker_path_msys)}; fi"
                ),
                f"cd {self._bash_quote(build_root_msys)}",
                'echo "Configuring Squid..."',
                (
                    f"{self._bash_quote(source_root_msys + '/configure')} "
                    f"{configure_argument_text} || exit $?"
                ),
                "if [ -f confdefs.h ]; then cp confdefs.h squid4win-confdefs.h; fi",
            )
        )
        self._run_bash(configure_lines, "Squid configure failed.")

        repair_result = self._repair_autoconf_header(
            generated_header_path, confdefs_copy_path, config_log_path
        )
        if repair_result["repaired_macros"]:
            self.output.info(
                "Repaired generated autoconf macros: "
                + ", ".join(repair_result["repaired_macros"])
            )

        build_lines = list(bash_common_lines)
        build_lines.extend(
            (
                f"cd {self._bash_quote(build_root_msys)}",
                'echo "Building Squid..."',
                f"make -j{self._make_jobs()} || exit $?",
                f"cd {self._bash_quote(build_root_msys)}",
                'echo "Installing Squid..."',
                "make install || exit $?",
            )
        )
        self._run_bash(build_lines, "MSYS2 build failed.")

        self._augment_bundle(
            bundle_root,
            source_root,
            metadata,
            configuration_label,
            build_settings,
            msys2_env_directory,
        )
        self._mirror_local_stage_root(bundle_root)

    def package(self) -> None:
        bundle_root = Path(self.build_folder) / "bundle"
        if not bundle_root.is_dir():
            raise ConanException(
                f"Expected the assembled bundle root at {bundle_root}."
            )

        copy(self, "*", src=os.fspath(bundle_root), dst=self.package_folder)
        for relative_directory in ("var\\cache", "var\\logs", "var\\run"):
            mkdir(self, os.path.join(self.package_folder, relative_directory))

    def package_info(self) -> None:
        self.cpp_info.bindirs = [".", "bin", "sbin"]
        self.runenv_info.prepend_path("PATH", self.package_folder)
        self.runenv_info.prepend_path(
            "PATH", os.path.join(self.package_folder, "bin")
        )
        self.runenv_info.prepend_path(
            "PATH", os.path.join(self.package_folder, "sbin")
        )

    def _augment_bundle(
        self,
        bundle_root: Path,
        source_root: Path,
        metadata: dict[str, object],
        configuration_label: str,
        build_settings: dict[str, object],
        msys2_env_directory: str,
    ) -> None:
        if self._option_enabled("with_tray"):
            tray_package_root = self._tray_package_root()
            tray_bin_root = tray_package_root / "bin"
            if not tray_bin_root.is_dir():
                raise ConanException(
                    f"Expected the tray package binaries at {tray_bin_root}."
                )

            self._copy_directory_contents(tray_bin_root, bundle_root)

            tray_executable = bundle_root / "Squid4Win.Tray.exe"
            if not tray_executable.is_file():
                raise ConanException(
                    f"Expected the bundled tray executable at {tray_executable}."
                )

        bundled_runtime_dlls: list[str] = []
        runtime_notice_packages: list[dict[str, object]] = []
        tray_third_party_packages: list[dict[str, object]] = []
        if self._option_enabled("with_runtime_dlls"):
            bundled_runtime_dlls = self._bundle_native_runtime_dlls(
                bundle_root, build_settings, msys2_env_directory
            )

        if self._option_enabled("with_packaging_support"):
            licenses_root = bundle_root / "licenses"
            installer_support_root = bundle_root / "installer"
            config_directory = bundle_root / "etc"
            for directory_path in (
                licenses_root,
                installer_support_root,
                config_directory,
            ):
                directory_path.mkdir(parents=True, exist_ok=True)

            shutil.copy2(
                Path(self.recipe_folder)
                / "scripts"
                / "installer"
                / "Manage-SquidService.ps1",
                installer_support_root / "svc.ps1",
            )
            shutil.copy2(
                Path(self.recipe_folder)
                / "packaging"
                / "defaults"
                / "squid.conf.template",
                config_directory / "squid.conf.template",
            )
            shutil.copy2(
                self._repository_license_path(),
                licenses_root / "Repository-LICENSE.txt",
            )

            mime_destination_path = config_directory / "mime.conf"
            if not mime_destination_path.is_file():
                mime_candidates = (
                    config_directory / "mime.conf.default",
                    source_root / "src" / "mime.conf.default",
                )
                mime_source_path = next(
                    (
                        candidate
                        for candidate in mime_candidates
                        if candidate.is_file()
                    ),
                    None,
                )
                if mime_source_path is None:
                    raise ConanException(
                        "Unable to locate mime.conf for the assembled bundle under "
                        f"{bundle_root}."
                    )
                shutil.copy2(mime_source_path, mime_destination_path)

            squid_copying_path = source_root / "COPYING"
            if squid_copying_path.is_file():
                shutil.copy2(squid_copying_path, licenses_root / "Squid-COPYING.txt")

            if bundled_runtime_dlls:
                runtime_notice_packages = self._harvest_runtime_notice_bundle(
                    bundle_root, build_settings, bundled_runtime_dlls
                )

            if self._option_enabled("with_tray"):
                tray_third_party_packages = self._collect_tray_notice_bundle(
                    bundle_root
                )

            source_manifest = {
                "generated_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "configuration": configuration_label,
                "squid": {
                    "version": str(metadata["version"]),
                    "tag": str(metadata["tag"]),
                    "source_archive": str(metadata["assets"]["source_archive"]),
                    "source_signature": str(
                        metadata["assets"].get("source_signature", "")
                    ),
                    "source_archive_sha256": str(
                        metadata["assets"]["source_archive_sha256"]
                    ),
                },
                "repository": {"name": "squid4win", "license": "MIT"},
                "windows_runtime": {
                    "msys2_env": msys2_env_directory,
                    "dlls": bundled_runtime_dlls,
                    "packages": runtime_notice_packages,
                },
            }
            if self._option_enabled("with_tray"):
                source_manifest["tray"] = {
                    "package": self._dependency_reference("squid4win_tray")
                    or "squid4win_tray/0.1",
                    "third_party_packages": tray_third_party_packages,
                }
            save(
                self,
                os.fspath(licenses_root / "source-manifest.json"),
                json.dumps(source_manifest, indent=2) + "\n",
                encoding="ascii",
            )

            notices_content = "\n".join(
                self._third_party_notice_lines(
                    metadata,
                    runtime_notice_packages,
                    tray_third_party_packages,
                )
            )
            save(
                self,
                os.fspath(bundle_root / "THIRD-PARTY-NOTICES.txt"),
                notices_content + "\n",
                encoding="ascii",
            )

        squid_candidates = (
            bundle_root / "sbin" / "squid.exe",
            bundle_root / "bin" / "squid.exe",
        )
        squid_executable = next(
            (candidate for candidate in squid_candidates if candidate.is_file()), None
        )
        if squid_executable is None:
            raise ConanException(
                f"Expected squid.exe under the assembled bundle root {bundle_root}."
            )

    def _bundle_native_runtime_dlls(
        self,
        bundle_root: Path,
        build_settings: dict[str, object],
        msys2_env_directory: str,
    ) -> list[str]:
        runtime_dlls = self._string_list(build_settings.get("runtime_dlls", []))
        if not runtime_dlls:
            raise ConanException(
                "conandata.yml must declare build.runtime_dlls for the staged "
                "Windows bundle."
            )

        runtime_dll_sources = self._runtime_dll_source_directories(msys2_env_directory)
        executable_directories = self._native_executable_directories(bundle_root)
        copied_runtime_dlls: list[str] = []
        missing_runtime_dlls: list[str] = []
        for runtime_dll in runtime_dlls:
            runtime_dll_source_path = next(
                (
                    source_directory / runtime_dll
                    for source_directory in runtime_dll_sources
                    if (source_directory / runtime_dll).is_file()
                ),
                None,
            )
            if runtime_dll_source_path is None:
                missing_runtime_dlls.append(runtime_dll)
                continue

            for executable_directory in executable_directories:
                shutil.copy2(
                    runtime_dll_source_path, executable_directory / runtime_dll
                )
            copied_runtime_dlls.append(runtime_dll)

        if missing_runtime_dlls:
            raise ConanException(
                "Unable to locate the required Windows runtime DLLs in the Conan "
                "dependency graph: "
                f"{', '.join(missing_runtime_dlls)}."
            )

        destination_labels = [
            "."
            if executable_directory == bundle_root
            else os.fspath(executable_directory.relative_to(bundle_root))
            for executable_directory in executable_directories
        ]
        source_labels = ", ".join(
            os.fspath(source_directory) for source_directory in runtime_dll_sources
        )
        self.output.info(
            "Bundled native runtime DLLs from "
            f"{source_labels} into {', '.join(destination_labels)}."
        )
        return copied_runtime_dlls

    def _harvest_runtime_notice_bundle(
        self,
        bundle_root: Path,
        build_settings: dict[str, object],
        bundled_runtime_dlls: list[str],
    ) -> list[dict[str, object]]:
        raw_notice_entries = list(build_settings.get("runtime_notice_artifacts", []))
        if not raw_notice_entries:
            raise ConanException(
                "conandata.yml must declare build.runtime_notice_artifacts for the staged Windows runtime notice bundle."
            )

        notice_root = bundle_root / "licenses" / "third-party" / "windows-runtime"
        bundled_runtime_dll_set = set(bundled_runtime_dlls)
        declared_runtime_dlls: set[str] = set()
        harvested_notice_entries: list[dict[str, object]] = []
        for raw_notice_entry in raw_notice_entries:
            notice_entry = dict(raw_notice_entry)
            notice_id = str(notice_entry.get("id", "")).strip()
            if not notice_id:
                raise ConanException(
                    "Each build.runtime_notice_artifacts entry in conandata.yml must declare a non-empty id."
                )

            runtime_dlls = self._deduplicate(
                self._string_list(notice_entry.get("dlls", []))
            )
            if not runtime_dlls:
                raise ConanException(
                    f"Runtime notice entry '{notice_id}' must declare at least one bundled DLL."
                )

            declared_runtime_dlls.update(runtime_dlls)
            dependency_name = str(notice_entry.get("dependency", "")).strip()
            if not dependency_name:
                raise ConanException(
                    f"Runtime notice entry '{notice_id}' must declare a dependency source."
                )

            dependency_root = self._dependency_package_root(dependency_name)
            if dependency_root is None:
                raise ConanException(
                    f"Unable to locate the '{dependency_name}' dependency package for runtime notice entry '{notice_id}'."
                )

            destination_root = notice_root / notice_id
            destination_root.mkdir(parents=True, exist_ok=True)
            copied_notice_files: list[str] = []
            for relative_path in self._deduplicate(
                self._string_list(notice_entry.get("license_files", []))
            ):
                source_path = dependency_root / Path(relative_path)
                if not source_path.is_file():
                    raise ConanException(
                        f"Unable to locate the runtime notice file '{relative_path}' for entry '{notice_id}' under {dependency_root}."
                    )

                destination_path = destination_root / source_path.name
                shutil.copy2(source_path, destination_path)
                copied_notice_files.append(
                    os.fspath(destination_path.relative_to(bundle_root)).replace(
                        "\\", "/"
                    )
                )

            if not copied_notice_files:
                raise ConanException(
                    f"Runtime notice entry '{notice_id}' did not resolve any notice files."
                )

            harvested_notice_entries.append(
                {
                    "id": notice_id,
                    "name": str(notice_entry.get("name", notice_id)).strip(),
                    "package": str(notice_entry.get("package", notice_id)).strip(),
                    "source_dependency": self._dependency_reference(dependency_name)
                    or dependency_name,
                    "license": str(notice_entry.get("license", "")).strip(),
                    "project_url": str(notice_entry.get("project_url", "")).strip(),
                    "dlls": runtime_dlls,
                    "notice_files": copied_notice_files,
                }
            )

        missing_notice_entries = sorted(bundled_runtime_dll_set - declared_runtime_dlls)
        if missing_notice_entries:
            raise ConanException(
                "The bundled Windows runtime DLLs are missing notice mappings in conandata.yml: "
                + ", ".join(missing_notice_entries)
                + "."
            )

        unused_notice_entries = sorted(declared_runtime_dlls - bundled_runtime_dll_set)
        if unused_notice_entries:
            raise ConanException(
                "build.runtime_notice_artifacts declares DLLs that were not bundled into the staged payload: "
                + ", ".join(unused_notice_entries)
                + "."
            )

        return harvested_notice_entries

    def _collect_tray_notice_bundle(
        self, bundle_root: Path
    ) -> list[dict[str, object]]:
        tray_package_root = self._tray_package_root()
        manifest_path = tray_package_root / "licenses" / "third-party-package-manifest.json"
        if not manifest_path.is_file():
            raise ConanException(
                f"Expected the tray third-party notice manifest at {manifest_path}."
            )

        manifest = json.loads(load(self, os.fspath(manifest_path)))
        tray_notice_packages: list[dict[str, object]] = []
        for raw_package in manifest.get("packages", []):
            package_entry = dict(raw_package)
            copied_notice_files: list[str] = []
            for notice_file in self._deduplicate(
                self._string_list(package_entry.get("notice_files", []))
            ):
                source_path = tray_package_root / Path(notice_file)
                if not source_path.is_file():
                    raise ConanException(
                        f"Unable to locate the tray third-party notice file '{notice_file}' under {tray_package_root}."
                    )

                destination_path = bundle_root / Path(notice_file)
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination_path)
                copied_notice_files.append(
                    os.fspath(destination_path.relative_to(bundle_root)).replace(
                        "\\", "/"
                    )
                )

            package_entry["notice_files"] = copied_notice_files
            package_entry["shipped_assets"] = self._deduplicate(
                self._string_list(package_entry.get("shipped_assets", []))
            )
            tray_notice_packages.append(package_entry)

        return tray_notice_packages

    @staticmethod
    def _third_party_notice_lines(
        metadata: dict[str, object],
        runtime_notice_packages: list[dict[str, object]],
        tray_third_party_packages: list[dict[str, object]],
    ) -> list[str]:
        notice_lines = [
            "Squid4Win third-party notice bundle",
            "",
            f"This payload stages Squid {metadata['version']} from the upstream source archive listed in licenses/source-manifest.json.",
            "Repository-local automation and packaging code in this project are MIT-licensed; see licenses/Repository-LICENSE.txt.",
            "",
            "Bundled notice files:",
            "- licenses/source-manifest.json",
            "- licenses/Repository-LICENSE.txt",
            "- licenses/Squid-COPYING.txt (when the upstream source tree is available locally)",
        ]

        if runtime_notice_packages or tray_third_party_packages:
            notice_lines.extend(
                (
                    "",
                    "Bundled third-party components:",
                    "- Squid upstream sources and license text: licenses/Squid-COPYING.txt",
                )
            )
            for notice_entry in runtime_notice_packages:
                asset_list = ", ".join(
                    [
                        str(asset).strip()
                        for asset in notice_entry.get("dlls", [])
                        if str(asset).strip()
                    ]
                )
                entry_line = (
                    f"- {notice_entry.get('name', notice_entry.get('id', 'runtime'))}"
                    f" [{asset_list}]"
                )
                if notice_entry.get("license"):
                    entry_line += f" - license: {notice_entry['license']}"
                if notice_entry.get("source_dependency"):
                    entry_line += f"; source: {notice_entry['source_dependency']}"
                notice_lines.append(entry_line)
                for notice_file in notice_entry.get("notice_files", []):
                    notice_lines.append(f"  - {notice_file}")

            for package_entry in tray_third_party_packages:
                asset_list = ", ".join(
                    [
                        str(asset).strip()
                        for asset in package_entry.get("shipped_assets", [])
                        if str(asset).strip()
                    ]
                )
                entry_line = (
                    f"- {package_entry.get('id', 'tray-package')}"
                    f" {package_entry.get('version', '')}"
                ).rstrip()
                if asset_list:
                    entry_line += f" [{asset_list}]"
                if package_entry.get("license"):
                    entry_line += f" - license: {package_entry['license']}"
                entry_line += "; source: NuGet package"
                notice_lines.append(entry_line)
                for notice_file in package_entry.get("notice_files", []):
                    notice_lines.append(f"  - {notice_file}")

        notice_lines.extend(
            (
                "",
                "Machine-readable provenance for the staged payload lives in licenses/source-manifest.json.",
            )
        )
        return notice_lines

    def _mirror_local_stage_root(self, bundle_root: Path) -> None:
        local_stage_root = self._local_stage_root()
        if local_stage_root is None:
            return

        shutil.rmtree(local_stage_root, ignore_errors=True)
        local_stage_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_root, local_stage_root, dirs_exist_ok=True)
        self.output.info(f"Mirrored the assembled bundle to {local_stage_root}.")

    @staticmethod
    def _native_executable_directories(bundle_root: Path) -> list[Path]:
        executable_directories = sorted(
            {executable_path.parent for executable_path in bundle_root.rglob("*.exe")},
            key=lambda path: os.fspath(path).lower(),
        )
        if not executable_directories:
            raise ConanException(
                f"Expected at least one executable under the assembled bundle root {bundle_root}."
            )

        return executable_directories

    def _runtime_dll_source_directories(
        self, msys2_env_directory: str
    ) -> list[Path]:
        source_directories: list[Path] = []
        seen_directories: set[str] = set()

        mingw_package_root = self._dependency_package_root("mingw-builds")
        if mingw_package_root is not None:
            self._append_existing_directory(
                source_directories, seen_directories, mingw_package_root / "bin"
            )

        msys2_package_root = self._dependency_package_root("msys2")
        if msys2_package_root is not None:
            self._append_existing_directory(
                source_directories,
                seen_directories,
                msys2_package_root / "bin" / "msys64" / msys2_env_directory / "bin",
            )
            self._append_existing_directory(
                source_directories,
                seen_directories,
                msys2_package_root / "bin" / "msys64" / "usr" / "bin",
            )

        for dependency in self.dependencies.values():
            package_folder = getattr(dependency, "package_folder", None)
            if not package_folder:
                continue

            package_root = Path(package_folder)
            for bindir in getattr(dependency.cpp_info, "bindirs", []):
                bindir_path = Path(bindir)
                if not bindir_path.is_absolute():
                    bindir_path = package_root / bindir_path
                self._append_existing_directory(
                    source_directories, seen_directories, bindir_path
                )

        if not source_directories:
            raise ConanException(
                "Unable to locate any runtime DLL source directories from the Conan "
                "dependency graph."
            )

        return source_directories

    @staticmethod
    def _append_existing_directory(
        directories: list[Path], seen_directories: set[str], candidate: Path
    ) -> None:
        if not candidate.is_dir():
            return

        candidate_key = os.path.normcase(os.fspath(candidate.resolve(strict=False)))
        if candidate_key in seen_directories:
            return

        seen_directories.add(candidate_key)
        directories.append(candidate)

    def _tray_package_root(self) -> Path:
        dependency_root = self._dependency_package_root("squid4win_tray")
        if dependency_root is not None:
            return dependency_root

        raise ConanException(
            "The squid4win_tray package dependency is not available to the root recipe."
        )

    def _dependency_package_root(self, dependency_name: str) -> Path | None:
        try:
            dependency = self.dependencies[dependency_name]
            return Path(dependency.package_folder)
        except Exception:
            for dependency in self.dependencies.values():
                dependency_ref = getattr(dependency, "ref", None)
                if dependency_ref and getattr(dependency_ref, "name", None) == dependency_name:
                    return Path(dependency.package_folder)

        return None

    def _dependency_reference(self, dependency_name: str) -> str | None:
        try:
            dependency = self.dependencies[dependency_name]
            dependency_ref = getattr(dependency, "ref", None)
            if dependency_ref:
                return str(dependency_ref)
        except Exception:
            for dependency in self.dependencies.values():
                dependency_ref = getattr(dependency, "ref", None)
                if dependency_ref and getattr(dependency_ref, "name", None) == dependency_name:
                    return str(dependency_ref)

        return None

    def _repository_license_path(self) -> Path:
        local_license_path = Path(self.recipe_folder) / "LICENSE"
        if local_license_path.is_file():
            return local_license_path

        exported_license_path = Path(self.recipe_folder) / "licenses" / "LICENSE"
        if exported_license_path.is_file():
            return exported_license_path

        raise ConanException(
            f"Unable to locate the repository license under {self.recipe_folder}."
        )

    def _configure_cache_lines(self, build_settings: dict[str, object]) -> list[str]:
        configure_cache = build_settings.get("configure_cache")
        if not configure_cache:
            return []

        configure_cache_lines = [
            "# Generated by the squid4win Conan recipe to stabilize native MSYS2/MinGW-w64 configure checks."
        ]
        for cache_name, cache_value in dict(configure_cache).items():
            name = str(cache_name).strip()
            value = str(cache_value).strip()
            if name and value:
                configure_cache_lines.append(f"{name}={value}")

        return configure_cache_lines

    def _additional_configure_args(self) -> list[str]:
        raw_value = os.getenv("SQUID4WIN_CONFIGURE_ARGS_JSON", "").strip()
        if not raw_value:
            return []

        parsed_value = json.loads(raw_value)
        return self._string_list(parsed_value)

    @staticmethod
    def _deduplicate(values: list[str]) -> list[str]:
        deduplicated_values: list[str] = []
        for value in values:
            if value not in deduplicated_values:
                deduplicated_values.append(value)

        return deduplicated_values

    @staticmethod
    def _bash_quote(value: object) -> str:
        return "'" + str(value).replace("'", "'\"'\"'") + "'"

    def _option_enabled(self, option_name: str) -> bool:
        return str(getattr(self.options, option_name)).lower() == "true"

    def _run_bash(self, lines: list[str], failure_message: str) -> None:
        bash_path = str(self.conf.get("tools.microsoft.bash:path", default="")).strip()
        if not bash_path:
            raise ConanInvalidConfiguration(
                "The profile must define tools.microsoft.bash:path for the MSYS2 build."
            )

        result = subprocess.run(
            [bash_path, "-lc", "; ".join(lines)],
            check=False,
        )
        if result.returncode != 0:
            raise ConanException(
                f"{failure_message} The bash command exited with code {result.returncode}."
            )

    @staticmethod
    def _make_jobs() -> int:
        raw_value = os.getenv("SQUID4WIN_MAKE_JOBS", "1").strip()
        try:
            make_jobs = int(raw_value)
        except ValueError as exc:
            raise ConanException(
                f"SQUID4WIN_MAKE_JOBS must be an integer, but was '{raw_value}'."
            ) from exc

        if make_jobs < 1:
            raise ConanException("SQUID4WIN_MAKE_JOBS must be greater than zero.")

        return make_jobs

    def _repair_autoconf_header(
        self, generated_header_path: Path, confdefs_path: Path, config_log_path: Path
    ) -> dict[str, object]:
        if not generated_header_path.is_file():
            raise ConanException(
                f"Generated autoconf header was not found at {generated_header_path}."
            )

        header_text = load(self, os.fspath(generated_header_path))
        newline = "\r\n" if "\r\n" in header_text else "\n"
        has_trailing_newline = header_text.endswith(newline)
        definition_source_label, definition_lines = self._definition_source_lines(
            confdefs_path, config_log_path
        )
        definitions = self._parse_autoconf_definitions(definition_lines, newline)

        updated_lines: list[str] = []
        repaired_macros: list[str] = []

        for header_line in header_text.splitlines():
            updated_lines.append(
                self._repair_autoconf_header_line(
                    header_line, definitions, repaired_macros
                )
            )

        updated_header_text = newline.join(updated_lines)
        if has_trailing_newline:
            updated_header_text += newline

        if updated_header_text != header_text:
            save(
                self,
                os.fspath(generated_header_path),
                updated_header_text,
                encoding="utf-8",
            )

        return {
            "definition_source": definition_source_label,
            "repaired_macros": repaired_macros,
        }

    def _repair_autoconf_header_line(
        self,
        header_line: str,
        definitions: dict[str, dict[str, str]],
        repaired_macros: list[str],
    ) -> str:
        macro_name = self._macro_name_from_header_line(header_line)
        if macro_name is None or macro_name not in definitions:
            return header_line

        replacement_line = self._format_autoconf_definition(definitions[macro_name])
        if header_line != replacement_line and macro_name not in repaired_macros:
            repaired_macros.append(macro_name)

        return replacement_line

    @staticmethod
    def _format_autoconf_definition(definition: dict[str, str]) -> str:
        replacement_line = f"#define {definition['name']}{definition['parameter_text']}"
        if definition["value"]:
            replacement_line += f" {definition['value']}"

        return replacement_line

    @classmethod
    def _macro_name_from_header_line(cls, header_line: str) -> str | None:
        stripped_line = header_line.strip()
        if stripped_line.startswith("/*") and stripped_line.endswith("*/"):
            inner_line = stripped_line[2:-2].strip()
            if inner_line.startswith("#undef "):
                macro_name, _ = cls._split_macro_token(
                    inner_line[len("#undef ") :].strip()
                )
                return macro_name
            return None

        for directive in ("#define", "#undef"):
            directive_prefix = f"{directive} "
            if stripped_line.startswith(directive_prefix):
                macro_name, _ = cls._split_macro_token(
                    stripped_line[len(directive_prefix) :].strip()
                )
                return macro_name

        return None

    def _definition_source_lines(
        self, confdefs_path: Path, config_log_path: Path
    ) -> tuple[str, list[str]]:
        if confdefs_path.is_file():
            return "confdefs.h", load(self, os.fspath(confdefs_path)).splitlines()

        if config_log_path.is_file():
            config_log_lines = load(self, os.fspath(config_log_path)).splitlines()
            return "config.log", [
                re.sub(r"^\s*\|\s?", "", line) for line in config_log_lines
            ]

        raise ConanException(
            f"No autoconf definition source was found. Checked {confdefs_path} and {config_log_path}."
        )

    @staticmethod
    def _is_valid_macro_name(macro_name: str) -> bool:
        return bool(MACRO_NAME_PATTERN.fullmatch(macro_name))

    @classmethod
    def _split_macro_token(cls, token_text: str) -> tuple[str | None, str]:
        if not token_text:
            return None, ""

        macro_token = token_text.split(None, 1)[0]
        if "(" in macro_token:
            macro_name, parameter_suffix = macro_token.split("(", 1)
            parameter_text = f"({parameter_suffix}"
        else:
            macro_name = macro_token
            parameter_text = ""

        if not cls._is_valid_macro_name(macro_name):
            return None, ""

        return macro_name, parameter_text

    @classmethod
    def _parse_define_directive(
        cls, definition_line: str
    ) -> tuple[str, str, list[str]] | None:
        stripped_line = definition_line.lstrip()
        directive_prefix = "#define "
        if not stripped_line.startswith(directive_prefix):
            return None

        remainder = stripped_line[len(directive_prefix) :].strip()
        if not remainder:
            return None

        split_segments = remainder.split(None, 1)
        macro_name, parameter_text = cls._split_macro_token(split_segments[0])
        if macro_name is None:
            return None

        macro_value = split_segments[1] if len(split_segments) > 1 else ""
        return macro_name, parameter_text, [macro_value]

    @staticmethod
    def _parse_autoconf_definitions(
        definition_lines: list[str], newline: str
    ) -> dict[str, dict[str, str]]:
        definitions: dict[str, dict[str, str]] = {}
        current_name: str | None = None
        current_parameter_text = ""
        current_value_lines: list[str] = []

        def commit_current_definition() -> None:
            if current_name is None:
                return

            definitions[current_name] = {
                "name": current_name,
                "parameter_text": current_parameter_text,
                "value": newline.join(current_value_lines),
            }

        for definition_line in definition_lines:
            if current_name is not None:
                current_value_lines.append(definition_line)
                if not definition_line.rstrip().endswith("\\"):
                    commit_current_definition()
                    current_name = None
                    current_parameter_text = ""
                    current_value_lines = []
                continue

            parsed_directive = Squid4WinConan._parse_define_directive(definition_line)
            if parsed_directive is None:
                continue

            current_name, current_parameter_text, current_value_lines = (
                parsed_directive
            )
            if not definition_line.rstrip().endswith("\\"):
                commit_current_definition()
                current_name = None
                current_parameter_text = ""
                current_value_lines = []

        if current_name is not None:
            commit_current_definition()

        return definitions
