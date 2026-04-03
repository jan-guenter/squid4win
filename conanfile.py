from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.env import VirtualBuildEnv
from conan.tools.files import (
    apply_conandata_patches,
    copy,
    export_conandata_patches,
    get,
    load,
    mkdir,
    save,
)
from conan.tools.gnu import AutotoolsDeps, AutotoolsToolchain, PkgConfigDeps

MACRO_NAME_PATTERN = re.compile(r"[A-Za-z_]\w*\Z", re.ASCII)


class Squid4WinConan(ConanFile):
    name = "squid4win"
    license = "GPL-2.0-or-later"
    url = "https://github.com/jan-guenter/squid4win"
    description = (
        "Conan 2 recipe for building native Windows Squid with Conan-managed "
        "MSYS2 and MinGW-w64."
    )
    topics = ("squid", "proxy", "windows", "msys2", "mingw")
    package_type = "application"
    settings = "os", "arch", "compiler", "build_type"
    no_copy_source = True
    options = {
        "with_openssl": [True, False],
        "openssl_source": ["system", "conan"],
        "libxml2_source": ["system", "conan"],
        "pcre2_source": ["system", "conan"],
        "zlib_source": ["system", "conan"],
        "enable_win32_service": [True, False],
        "enable_default_hostsfile": [True, False],
        "enable_strict_error_checking": [True, False],
        "enable_dependency_tracking": [True, False],
        "auth_basic_helpers": [None, "ANY"],
        "auth_digest_helpers": [None, "ANY"],
        "auth_negotiate_helpers": [None, "ANY"],
        "external_acl_helpers": [None, "ANY"],
    }
    default_options = {
        "with_openssl": True,
        "openssl_source": "system",
        "libxml2_source": "system",
        "pcre2_source": "system",
        "zlib_source": "system",
        "enable_win32_service": True,
        "enable_default_hostsfile": True,
        "enable_strict_error_checking": False,
        "enable_dependency_tracking": False,
        "auth_basic_helpers": "DB,NCSA,POP3,RADIUS,SMB,SSPI,fake",
        "auth_digest_helpers": "file",
        "auth_negotiate_helpers": "SSPI",
        "external_acl_helpers": "LM_group,SQL_session,delayer,wbinfo_group",
        "openssl/*:shared": True,
        "libxml2/*:shared": False,
        "pcre2/*:shared": False,
        "zlib/*:shared": False,
    }

    def set_version(self) -> None:
        self.version = self._sole_supported_version()

    def export_sources(self) -> None:
        export_conandata_patches(self)

    def layout(self) -> None:
        configuration_label = self._configuration_label()
        self.folders.source = os.path.join("sources", f"squid-{self.version}")
        self.folders.build = os.path.join("build", configuration_label)
        self.folders.generators = os.path.join("build", configuration_label, "conan")

    def validate(self) -> None:
        self._validate_native_windows()
        for option_name in (
            "auth_basic_helpers",
            "auth_digest_helpers",
            "auth_negotiate_helpers",
            "external_acl_helpers",
        ):
            if self._string_option(option_name) == "":
                raise ConanInvalidConfiguration(
                    f"{option_name} cannot be an empty string. Use None to disable "
                    "the corresponding helper family."
                )

    def build_requirements(self) -> None:
        for reference in self._string_list(
            self._build_settings().get("tool_requires", [])
        ):
            self.tool_requires(reference)

    def requirements(self) -> None:
        for dependency_name, dependency_settings in self._dependency_settings().items():
            if not self._dependency_uses_conan(dependency_name):
                continue

            conan_reference = str(dependency_settings.get("conan_reference", "")).strip()
            if not conan_reference:
                raise ConanInvalidConfiguration(
                    f"build.dependencies.{dependency_name} must declare conan_reference."
                )
            self.requires(conan_reference)

    def generate(self) -> None:
        VirtualBuildEnv(self).generate()
        AutotoolsDeps(self).generate()
        AutotoolsToolchain(self).generate()
        PkgConfigDeps(self).generate()

    def source(self) -> None:
        source_data = dict(self.conan_data["sources"][str(self.version)])
        strip_root = bool(source_data.pop("strip_root", True))
        source_root = Path(self.source_folder)
        source_ready_marker = source_root / ".source-ready"
        source_fingerprint = self._source_tree_fingerprint(
            source_data=source_data,
            strip_root=strip_root,
        )

        if source_ready_marker.is_file():
            recorded_fingerprint = source_ready_marker.read_text(encoding="ascii").strip()
            if recorded_fingerprint == source_fingerprint:
                self.output.info(f"Reusing existing source tree at {source_root}.")
                return
            self.output.info(
                "Refreshing the Squid source tree because the source metadata or "
                "patch set changed."
            )

        mkdir(self, self.source_folder)
        for child in source_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        get(self, destination=self.source_folder, strip_root=strip_root, **source_data)
        apply_conandata_patches(self)
        source_ready_marker.write_text(f"{source_fingerprint}\n", encoding="ascii")

    def build(self) -> None:
        build_settings = self._build_settings()
        source_root = Path(self.source_folder)
        build_root = Path(self.build_folder)
        install_root = build_root / "package"
        config_site_path = build_root / "config.site"
        bootstrap_marker_path = build_root / "bootstrap-ran"
        generated_header_path = build_root / "include" / "autoconf.h"
        confdefs_copy_path = build_root / "confdefs.generated.h"
        config_log_path = build_root / "config.log"
        msys2_settings = dict(build_settings.get("msys2", {}))
        msys2_env_directory = str(msys2_settings.get("env", "mingw64")).lower()
        msys2_env_name = msys2_env_directory.upper()
        msys2_prefix_path = f"/{msys2_env_directory}"
        pkg_config_binary_path = f"/{msys2_env_directory}/bin/pkg-config"
        pkg_config_lib_dir = (
            f"/{msys2_env_directory}/lib/pkgconfig"
            f":/{msys2_env_directory}/share/pkgconfig"
        )
        build_env_script = Path(self.generators_folder) / "conanbuild.sh"
        autotools_deps_script = Path(self.generators_folder) / "conanautotoolsdeps.sh"
        autotools_script = Path(self.generators_folder) / "conanautotoolstoolchain.sh"

        shutil.rmtree(install_root, ignore_errors=True)
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

        host_triplet = str(build_settings["host_triplet"])
        configure_arguments = self._deduplicate(
            [
                f"--prefix={self._to_msys_path(install_root)}",
                f"--build={host_triplet}",
                f"--host={host_triplet}",
                *self._string_list(build_settings.get("configure_args", [])),
                *self._recipe_configure_args(),
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
                "The mingw-builds tool requirement is not available to the recipe."
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
        conan_dependency_roots = self._conan_dependency_package_roots()
        conan_dependency_bin_roots_msys = self._deduplicate(
            [
                self._to_msys_path(dependency_root / "bin")
                for dependency_root in conan_dependency_roots.values()
                if (dependency_root / "bin").is_dir()
            ]
        )
        pkg_config_path_entries = []
        if conan_dependency_roots:
            pkg_config_path_entries.append(self._to_msys_path(self.generators_folder))
        for dependency_root in conan_dependency_roots.values():
            for pkg_config_root in (
                dependency_root / "lib" / "pkgconfig",
                dependency_root / "share" / "pkgconfig",
            ):
                if pkg_config_root.is_dir():
                    pkg_config_path_entries.append(self._to_msys_path(pkg_config_root))
        pkg_config_path_entries = self._deduplicate(pkg_config_path_entries)
        path_entries = self._deduplicate(
            [
                *conan_dependency_bin_roots_msys,
                mingw_bin_root_msys,
                f"/{msys2_env_directory}/bin",
                "$MSYS_BIN",
                "/usr/bin",
                "/usr/bin/core_perl",
                "$PATH",
            ]
        )

        bash_common_lines = [
            f"export MSYSTEM={msys2_env_name}",
            "export CHERE_INVOKING=1",
            "set -o pipefail",
        ]
        for generated_script in (build_env_script, autotools_deps_script, autotools_script):
            if generated_script.is_file():
                bash_common_lines.append(
                    f"source {self._bash_quote(self._to_msys_path(generated_script))}"
                )

        bash_common_lines.extend(
            (
                "source /etc/profile",
                f'export PATH="{":".join(path_entries)}"',
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
        if pkg_config_path_entries:
            bash_common_lines.append(
                f'export PKG_CONFIG_PATH="{":".join(pkg_config_path_entries)}'
                '${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"'
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
                    "then ./bootstrap.sh || exit $?; "
                    f"touch {self._bash_quote(bootstrap_marker_path_msys)}; fi"
                ),
                f"cd {self._bash_quote(build_root_msys)}",
                'echo "Configuring Squid..."',
                (
                    f"{self._bash_quote(source_root_msys + '/configure')} "
                    f"{configure_argument_text} || exit $?"
                ),
                "if [ -f confdefs.h ]; then cp confdefs.h confdefs.generated.h; fi",
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
                f"make -j{self._build_jobs()} || exit $?",
                f"cd {self._bash_quote(build_root_msys)}",
                'echo "Installing Squid..."',
                "make install || exit $?",
            )
        )
        self._run_bash(build_lines, "MSYS2 build failed.")
        self._require_squid_executable(install_root)

    def package(self) -> None:
        install_root = Path(self.build_folder) / "package"
        if not install_root.is_dir():
            raise ConanException(
                f"Expected the native Squid install root at {install_root}."
            )

        upstream_license_path = Path(self.source_folder) / "COPYING"
        if not upstream_license_path.is_file():
            raise ConanException(
                f"Expected the upstream Squid license at {upstream_license_path}."
            )

        copy(self, "*", src=os.fspath(install_root), dst=self.package_folder)
        copy(
            self,
            "COPYING",
            src=self.source_folder,
            dst=os.path.join(self.package_folder, "licenses"),
        )

    def package_info(self) -> None:
        self.cpp_info.bindirs = ["bin", "sbin", "libexec"]
        for bindir in self.cpp_info.bindirs:
            self.runenv_info.prepend_path("PATH", os.path.join(self.package_folder, bindir))

    def _sole_supported_version(self) -> str:
        source_entries = self.conan_data.get("sources")
        if not isinstance(source_entries, dict) or not source_entries:
            raise ConanInvalidConfiguration(
                "conandata.yml must define exactly one supported source version."
            )

        source_versions = [
            str(version).strip() for version in source_entries.keys() if str(version).strip()
        ]
        if len(source_versions) != 1:
            raise ConanInvalidConfiguration(
                "conandata.yml must define exactly one supported source version."
            )

        return source_versions[0]

    def _source_tree_fingerprint(
        self,
        *,
        source_data: dict[str, object],
        strip_root: bool,
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(
            json.dumps(
                {
                    "version": str(self.version),
                    "strip_root": strip_root,
                    "source": source_data,
                },
                sort_keys=True,
            ).encode("utf-8")
        )
        for patch_entry in self.conan_data.get("patches", {}).get(str(self.version), []):
            normalized_patch_entry = dict(patch_entry)
            patch_path = Path(self.recipe_folder) / str(
                normalized_patch_entry["patch_file"]
            )
            hasher.update(
                json.dumps(normalized_patch_entry, sort_keys=True).encode("utf-8")
            )
            hasher.update(patch_path.read_bytes())
        return hasher.hexdigest()

    def _build_settings(self) -> dict[str, object]:
        build_settings = self.conan_data.get("build")
        if not isinstance(build_settings, dict):
            raise ConanInvalidConfiguration(
                "conandata.yml must define a top-level 'build' mapping."
            )

        return build_settings

    def _dependency_settings(self) -> dict[str, dict[str, object]]:
        raw_dependencies = self._build_settings().get("dependencies", {})
        if not isinstance(raw_dependencies, dict):
            raise ConanInvalidConfiguration(
                "conandata.yml build.dependencies must be a mapping."
            )

        dependency_settings: dict[str, dict[str, object]] = {}
        for dependency_name, raw_dependency in raw_dependencies.items():
            normalized_name = str(dependency_name).strip()
            if not normalized_name:
                continue
            if not isinstance(raw_dependency, dict):
                raise ConanInvalidConfiguration(
                    f"build.dependencies.{normalized_name} must be a mapping."
                )
            dependency_settings[normalized_name] = dict(raw_dependency)

        return dependency_settings

    def _dependency_source(self, dependency_name: str) -> str:
        dependency_settings = self._dependency_settings().get(dependency_name)
        if dependency_settings is None:
            raise ConanInvalidConfiguration(
                f"build.dependencies.{dependency_name} was not defined in conandata.yml."
            )

        option_name = str(dependency_settings.get("source_option", "")).strip()
        if not option_name:
            raise ConanInvalidConfiguration(
                f"build.dependencies.{dependency_name} must declare source_option."
            )

        source_value = str(getattr(self.options, option_name, "")).strip().lower()
        if source_value not in {"system", "conan"}:
            raise ConanInvalidConfiguration(
                f"Unsupported source '{source_value}' for dependency '{dependency_name}'."
            )

        return source_value

    def _dependency_uses_conan(self, dependency_name: str) -> bool:
        dependency_settings = self._dependency_settings()[dependency_name]
        feature_option = str(dependency_settings.get("feature_option", "")).strip()
        if feature_option and not self._option_enabled(feature_option):
            return False
        return self._dependency_source(dependency_name) == "conan"

    def _conan_dependency_package_roots(self) -> dict[str, Path]:
        dependency_roots: dict[str, Path] = {}
        for dependency_name in self._dependency_settings():
            if not self._dependency_uses_conan(dependency_name):
                continue

            dependency_root = self._dependency_package_root(dependency_name)
            if dependency_root is None:
                raise ConanException(
                    f"The Conan dependency '{dependency_name}' is not available to the recipe."
                )
            dependency_roots[dependency_name] = dependency_root

        return dependency_roots

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
                "The squid4win recipe only supports native Windows builds."
            )

        if str(self.settings.arch) != "x86_64":
            raise ConanInvalidConfiguration("Only x86_64 builds are supported.")

        compiler = getattr(self.settings, "compiler", None)
        if compiler is not None and str(compiler) != "gcc":
            raise ConanInvalidConfiguration(
                "Use the Conan-managed MSYS2 MinGW-w64 GCC host profile."
            )

    @staticmethod
    def _to_msys_path(path: os.PathLike[str] | str) -> str:
        normalized_path = os.path.abspath(os.fspath(path)).replace("\\", "/")
        if len(normalized_path) >= 2 and normalized_path[1] == ":":
            return f"/{normalized_path[0].lower()}{normalized_path[2:]}"

        return normalized_path

    def _recipe_configure_args(self) -> list[str]:
        return [
            self._toggle_configure_arg(
                "with_openssl", "--with-openssl", "--without-openssl"
            ),
            self._toggle_configure_arg(
                "enable_win32_service",
                "--enable-win32-service",
                "--disable-win32-service",
            ),
            self._toggle_configure_arg(
                "enable_default_hostsfile",
                "--enable-default-hostsfile",
                "--disable-default-hostsfile",
            ),
            self._toggle_configure_arg(
                "enable_strict_error_checking",
                "--enable-strict-error-checking",
                "--disable-strict-error-checking",
            ),
            self._toggle_configure_arg(
                "enable_dependency_tracking",
                "--enable-dependency-tracking",
                "--disable-dependency-tracking",
            ),
            self._list_configure_arg("auth_basic_helpers", "auth-basic"),
            self._list_configure_arg("auth_digest_helpers", "auth-digest"),
            self._list_configure_arg("auth_negotiate_helpers", "auth-negotiate"),
            self._list_configure_arg("external_acl_helpers", "external-acl-helpers"),
        ]

    def _toggle_configure_arg(
        self, option_name: str, enabled_flag: str, disabled_flag: str
    ) -> str:
        return enabled_flag if self._option_enabled(option_name) else disabled_flag

    def _list_configure_arg(self, option_name: str, feature_name: str) -> str:
        option_value = self._string_option(option_name)
        if option_value is None:
            return f"--disable-{feature_name}"

        if not option_value:
            raise ConanInvalidConfiguration(
                f"{option_name} cannot be empty. Use None to disable {feature_name}."
            )

        return f"--enable-{feature_name}={option_value}"

    def _string_option(self, option_name: str) -> str | None:
        option_value = getattr(self.options, option_name)
        if option_value is None:
            return None

        option_text = str(option_value).strip()
        if option_text.lower() == "none":
            return None

        return option_text

    def _dependency_package_root(self, dependency_name: str) -> Path | None:
        try:
            dependency = self.dependencies[dependency_name]
            package_folder = getattr(dependency, "package_folder", None)
            if package_folder:
                return Path(package_folder)
        except Exception:
            pass

        for dependency in self.dependencies.values():
            dependency_ref = getattr(dependency, "ref", None)
            if dependency_ref and getattr(dependency_ref, "name", None) == dependency_name:
                package_folder = getattr(dependency, "package_folder", None)
                if package_folder:
                    return Path(package_folder)

        return None

    def _configure_cache_lines(self, build_settings: dict[str, object]) -> list[str]:
        configure_cache = build_settings.get("configure_cache")
        if not configure_cache:
            return []

        configure_cache_lines = [
            (
                "# Generated by the native Squid Conan recipe to stabilize "
                "MSYS2/MinGW-w64 configure checks."
            )
        ]
        for cache_name, cache_value in dict(configure_cache).items():
            name = str(cache_name).strip()
            value = str(cache_value).strip()
            if name and value:
                configure_cache_lines.append(f"{name}={value}")

        return configure_cache_lines

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

    def _build_jobs(self) -> int:
        raw_value = self.conf.get("tools.build:jobs", default=1)
        try:
            build_jobs = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ConanException(
                f"tools.build:jobs must be an integer, but was '{raw_value}'."
            ) from exc

        if build_jobs < 1:
            raise ConanException("tools.build:jobs must be greater than zero.")

        return build_jobs

    @staticmethod
    def _require_squid_executable(install_root: Path) -> Path:
        squid_candidates = (
            install_root / "sbin" / "squid.exe",
            install_root / "bin" / "squid.exe",
        )
        squid_executable = next(
            (candidate for candidate in squid_candidates if candidate.is_file()),
            None,
        )
        if squid_executable is None:
            raise ConanException(
                f"Expected squid.exe under the native install root {install_root}."
            )

        return squid_executable

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
            "No autoconf definition source was found. "
            f"Checked {confdefs_path} and {config_log_path}."
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
