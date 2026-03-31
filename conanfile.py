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
    rmdir,
    save,
)
from conan.tools.gnu import AutotoolsToolchain


class Squid4WinConan(ConanFile):
    name = "squid4win"
    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"
    no_copy_source = True
    python_requires = "squid4win_recipe_base/1.0"
    python_requires_extend = "squid4win_recipe_base.Squid4WinRecipeBase"

    def set_version(self) -> None:
        metadata = self._release_metadata()
        self.version = str(metadata["version"])

    def export(self) -> None:
        export_conandata_patches(self)
        copy(
            self,
            "build-profile.json",
            src=os.path.join(self.recipe_folder, "config"),
            dst=os.path.join(self.export_folder, "config"),
        )
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
        self.folders.generators = os.path.join("build", configuration_label, "conan")

    def validate(self) -> None:
        self._validate_native_windows()

    def requirements(self) -> None:
        self.requires("squid4win_tray/0.1")

        if self._conan_dependency_mode() != "managed":
            return

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
        metadata = self._release_metadata()
        build_profile = self._build_profile()

        VirtualBuildEnv(self).generate()
        VirtualRunEnv(self).generate()

        release_env = Environment()
        release_env.define("SQUID_VERSION", str(metadata["version"]))
        release_env.define("SQUID_TAG", str(metadata["tag"]))
        release_env.define(
            "SQUID_SOURCE_ARCHIVE", str(metadata["assets"]["source_archive"])
        )
        release_env.define(
            "SQUID_CONAN_REQUIREMENTS",
            ";".join(self._string_list(build_profile.get("conanRequirements", []))),
        )
        release_env.define(
            "SQUID_CONAN_TOOL_REQUIREMENTS",
            ";".join(
                self._string_list(build_profile.get("conanToolRequirements", []))
            ),
        )
        release_env.define(
            "SQUID_CONAN_DEPENDENCY_MODE", self._conan_dependency_mode()
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
        build_profile = self._build_profile()
        source_root = Path(self.source_folder)
        build_root = Path(self.build_folder)
        bundle_root = build_root / "bundle"
        config_site_path = build_root / "config.site"
        bootstrap_marker_path = build_root / "squid4win-bootstrap-ran"
        generated_header_path = build_root / "include" / "autoconf.h"
        confdefs_copy_path = build_root / "squid4win-confdefs.h"
        config_log_path = build_root / "config.log"
        configuration_label = self._configuration_label()
        msys2_env_directory = str(build_profile.get("msys2Env", "mingw64")).lower()
        msys2_env_name = str(build_profile.get("msys2Env", "mingw64")).upper()
        pkg_config_binary_path = f"/{msys2_env_directory}/bin/pkg-config"
        pkg_config_lib_dir = (
            f"/{msys2_env_directory}/lib/pkgconfig:/{msys2_env_directory}/share/pkgconfig"
        )
        autotools_script = Path(self.generators_folder) / "conanautotoolstoolchain.sh"
        release_script = Path(self.generators_folder) / "squid-release.sh"

        shutil.rmtree(bundle_root, ignore_errors=True)
        bootstrap_marker_path.unlink(missing_ok=True)
        build_root.mkdir(parents=True, exist_ok=True)

        configure_cache_lines = self._configure_cache_lines(build_profile)
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
                f"--build={str(build_profile['hostTriplet'])}",
                f"--host={str(build_profile['hostTriplet'])}",
                *self._string_list(build_profile.get("configureArgs", [])),
                *self._additional_configure_args(),
            ]
        )
        configure_argument_text = " ".join(
            self._bash_quote(argument) for argument in configure_arguments
        )
        source_root_msys = self._to_msys_path(source_root)
        build_root_msys = self._to_msys_path(build_root)
        bootstrap_marker_path_msys = self._to_msys_path(bootstrap_marker_path)

        bash_common_lines = [
            f"export MSYSTEM={msys2_env_name}",
            "export CHERE_INVOKING=1",
            "source /etc/profile",
            "set -o pipefail",
            f'export PATH="/{msys2_env_directory}/bin:/usr/bin:/usr/bin/core_perl:$PATH"',
        ]

        for generated_script in (autotools_script, release_script):
            if generated_script.is_file():
                bash_common_lines.append(
                    f"source {self._bash_quote(self._to_msys_path(generated_script))}"
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
            build_profile,
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
        build_profile: dict[str, object],
        msys2_env_directory: str,
    ) -> None:
        tray_package_root = self._tray_package_root()
        tray_bin_root = tray_package_root / "bin"
        if not tray_bin_root.is_dir():
            raise ConanException(
                f"Expected the tray package binaries at {tray_bin_root}."
            )

        self._copy_directory_contents(tray_bin_root, bundle_root)

        licenses_root = bundle_root / "licenses"
        installer_support_root = bundle_root / "installer"
        config_directory = bundle_root / "etc"
        for directory_path in (
            licenses_root,
            installer_support_root,
            config_directory,
            bundle_root / "var" / "cache",
            bundle_root / "var" / "logs",
            bundle_root / "var" / "run",
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
                (candidate for candidate in mime_candidates if candidate.is_file()), None
            )
            if mime_source_path is None:
                raise ConanException(
                    f"Unable to locate mime.conf for the assembled bundle under {bundle_root}."
                )
            shutil.copy2(mime_source_path, mime_destination_path)

        squid_copying_path = source_root / "COPYING"
        if squid_copying_path.is_file():
            shutil.copy2(squid_copying_path, licenses_root / "Squid-COPYING.txt")

        bundled_runtime_dlls = self._bundle_native_runtime_dlls(
            bundle_root, build_profile, msys2_env_directory
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
            },
        }
        save(
            self,
            os.fspath(licenses_root / "source-manifest.json"),
            json.dumps(source_manifest, indent=2) + "\n",
            encoding="ascii",
        )

        notices_content = "\n".join(
            (
                "Squid4Win third-party notice bundle",
                "",
                f"This payload stages Squid {metadata['version']} from the upstream source archive listed in licenses/source-manifest.json.",
                "Repository-local automation and packaging code in this project are MIT-licensed; see licenses/Repository-LICENSE.txt.",
                "",
                "Current bundled notice set:",
                "- licenses/source-manifest.json",
                "- licenses/Repository-LICENSE.txt",
                "- licenses/Squid-COPYING.txt (when the upstream source tree is available locally)",
                "",
                "Bundled native runtime DLLs are recorded in licenses/source-manifest.json.",
                "Before a signed production release, audit that runtime DLL set and expand this notice bundle with any additional third-party runtime licenses that ship in the installer.",
            )
        )
        save(
            self,
            os.fspath(bundle_root / "THIRD-PARTY-NOTICES.txt"),
            notices_content + "\n",
            encoding="ascii",
        )

        tray_executable = bundle_root / "Squid4Win.Tray.exe"
        if not tray_executable.is_file():
            raise ConanException(
                f"Expected the bundled tray executable at {tray_executable}."
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
        build_profile: dict[str, object],
        msys2_env_directory: str,
    ) -> list[str]:
        runtime_dlls = self._string_list(build_profile.get("runtimeDlls", []))
        if not runtime_dlls:
            raise ConanException(
                "build-profile.json must declare runtimeDlls for the staged Windows bundle."
            )

        msys2_runtime_bin = self._msys2_runtime_bin_path(
            build_profile, msys2_env_directory
        )
        executable_directories = self._native_executable_directories(bundle_root)
        copied_runtime_dlls: list[str] = []
        missing_runtime_dlls: list[str] = []
        for runtime_dll in runtime_dlls:
            runtime_dll_source_path = msys2_runtime_bin / runtime_dll
            if not runtime_dll_source_path.is_file():
                missing_runtime_dlls.append(runtime_dll)
                continue

            for executable_directory in executable_directories:
                shutil.copy2(
                    runtime_dll_source_path, executable_directory / runtime_dll
                )
            copied_runtime_dlls.append(runtime_dll)

        if missing_runtime_dlls:
            raise ConanException(
                "Unable to locate the required MSYS2 runtime DLLs under "
                f"{msys2_runtime_bin}: {', '.join(missing_runtime_dlls)}."
            )

        destination_labels = [
            "."
            if executable_directory == bundle_root
            else os.fspath(executable_directory.relative_to(bundle_root))
            for executable_directory in executable_directories
        ]
        self.output.info(
            "Bundled native runtime DLLs from "
            f"{msys2_runtime_bin} into {', '.join(destination_labels)}."
        )
        return copied_runtime_dlls

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

    def _msys2_runtime_bin_path(
        self, build_profile: dict[str, object], msys2_env_directory: str
    ) -> Path:
        candidate_roots: list[Path] = []
        seen_roots: set[str] = set()

        def add_candidate_root(path_value: object) -> None:
            if path_value is None:
                return

            candidate_text = str(path_value).strip()
            if not candidate_text:
                return

            candidate_path = Path(candidate_text)
            if not candidate_path.is_absolute():
                candidate_path = Path(self.recipe_folder) / candidate_path

            resolved_candidate_path = candidate_path.resolve(strict=False)
            candidate_key = os.path.normcase(os.fspath(resolved_candidate_path))
            if candidate_key in seen_roots:
                return

            seen_roots.add(candidate_key)
            candidate_roots.append(resolved_candidate_path)

        bash_path = str(self.conf.get("tools.microsoft.bash:path", default="")).strip()
        add_candidate_root(
            self._root_from_tool_path(bash_path, os.path.join("usr", "bin", "bash.exe"))
        )

        bash_command_path = shutil.which("bash.exe") or shutil.which("bash")
        add_candidate_root(
            self._root_from_tool_path(
                bash_command_path, os.path.join("usr", "bin", "bash.exe")
            )
        )

        gcc_command_path = shutil.which("gcc.exe") or shutil.which("gcc")
        add_candidate_root(
            self._root_from_tool_path(
                gcc_command_path,
                os.path.join(msys2_env_directory, "bin", "gcc.exe"),
            )
        )

        add_candidate_root(os.getenv("MSYS2_ROOT"))
        add_candidate_root(os.getenv("MSYS2_LOCATION"))

        runner_temp = str(os.getenv("RUNNER_TEMP", "")).strip()
        if runner_temp:
            add_candidate_root(Path(runner_temp) / "msys64")

        for hint in self._string_list(build_profile.get("msys2RootHints", [])):
            add_candidate_root(hint)

        for candidate_root in candidate_roots:
            runtime_bin_path = candidate_root / msys2_env_directory / "bin"
            if runtime_bin_path.is_dir():
                return runtime_bin_path

        searched_roots = ", ".join(os.fspath(candidate_root) for candidate_root in candidate_roots) or "none"
        raise ConanException(
            "Unable to locate the MSYS2 runtime bin directory for the staged bundle. "
            f"Searched: {searched_roots}."
        )

    @staticmethod
    def _root_from_tool_path(tool_path: str | None, suffix: str) -> Path | None:
        if not tool_path:
            return None

        resolved_tool_path = os.path.abspath(tool_path).replace("/", "\\")
        normalized_suffix = suffix.replace("/", "\\")
        if not resolved_tool_path.lower().endswith(normalized_suffix.lower()):
            return None

        root_text = resolved_tool_path[: -len(normalized_suffix)].rstrip("\\")
        if not root_text:
            return None

        return Path(root_text)

    def _tray_package_root(self) -> Path:
        try:
            dependency = self.dependencies["squid4win_tray"]
            return Path(dependency.package_folder)
        except Exception:
            for dependency in self.dependencies.values():
                dependency_ref = getattr(dependency, "ref", None)
                if dependency_ref and getattr(dependency_ref, "name", None) == "squid4win_tray":
                    return Path(dependency.package_folder)

        raise ConanException(
            "The squid4win_tray package dependency is not available to the root recipe."
        )

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

    def _conan_dependency_mode(self) -> str:
        mode = str(self._build_profile().get("conanDependencyMode", "managed")).strip()
        if mode not in {"managed", "metadata-only"}:
            raise ConanInvalidConfiguration(
                f"Unsupported conanDependencyMode '{mode}'."
            )

        return mode

    def _configure_cache_lines(self, build_profile: dict[str, object]) -> list[str]:
        configure_cache = build_profile.get("configureCache")
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
        macro_undef_pattern = re.compile(
            r"^\s*/\*\s*#undef\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?\s*\*/\s*$"
        )
        macro_definition_pattern = re.compile(
            r"^\s*#(?:define|undef)\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?\b.*$"
        )

        for header_line in header_text.splitlines():
            macro_match = macro_undef_pattern.match(header_line)
            if macro_match is None:
                macro_match = macro_definition_pattern.match(header_line)

            if macro_match is None:
                updated_lines.append(header_line)
                continue

            macro_name = macro_match.group(1)
            if macro_name not in definitions:
                updated_lines.append(header_line)
                continue

            definition = definitions[macro_name]
            replacement_line = f"#define {definition['name']}{definition['parameter_text']}"
            if definition["value"]:
                replacement_line += f" {definition['value']}"

            if header_line != replacement_line and macro_name not in repaired_macros:
                repaired_macros.append(macro_name)

            updated_lines.append(replacement_line)

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
    def _parse_autoconf_definitions(
        definition_lines: list[str], newline: str
    ) -> dict[str, dict[str, str]]:
        definitions: dict[str, dict[str, str]] = {}
        define_pattern = re.compile(
            r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?(?:\s+(.*))?$"
        )
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

            match = define_pattern.match(definition_line)
            if match is None:
                continue

            current_name = match.group(1)
            current_parameter_text = match.group(2) or ""
            current_value_lines = [match.group(3) or ""]
            if not definition_line.rstrip().endswith("\\"):
                commit_current_definition()
                current_name = None
                current_parameter_text = ""
                current_value_lines = []

        if current_name is not None:
            commit_current_definition()

        return definitions
