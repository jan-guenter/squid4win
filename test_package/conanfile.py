from __future__ import annotations

import json
from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException


class Squid4WinBundleTestPackage(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    test_type = "explicit"

    def requirements(self) -> None:
        self.requires(self.tested_reference_str)

    def test(self) -> None:
        package_name = self.tested_reference_str.split("/", 1)[0]
        dependency = self.dependencies[package_name]
        package_root = Path(dependency.package_folder)
        with_tray = str(dependency.options.get_safe("with_tray", False)).lower() == "true"
        with_runtime_dlls = (
            str(dependency.options.get_safe("with_runtime_dlls", False)).lower()
            == "true"
        )
        with_packaging_support = (
            str(
                dependency.options.get_safe("with_packaging_support", False)
            ).lower()
            == "true"
        )

        squid_candidates = (
            package_root / "sbin" / "squid.exe",
            package_root / "bin" / "squid.exe",
        )
        squid_executable = next(
            (candidate for candidate in squid_candidates if candidate.is_file()),
            None,
        )
        if squid_executable is None:
            raise ConanException(
                f"Expected squid.exe under {package_root}, but none was found."
            )

        if with_tray:
            tray_executable = package_root / "Squid4Win.Tray.exe"
            if not tray_executable.is_file():
                raise ConanException(
                    f"Expected the bundled tray executable at {tray_executable}."
                )

        notices_path = package_root / "THIRD-PARTY-NOTICES.txt"
        if with_packaging_support and not notices_path.is_file():
            raise ConanException(
                f"Expected the bundled third-party notices at {notices_path}."
            )

        source_manifest_path = package_root / "licenses" / "source-manifest.json"
        if with_packaging_support and not source_manifest_path.is_file():
            raise ConanException(
                f"Expected the bundled source manifest at {source_manifest_path}."
            )

        runtime_dlls: list[str] = []
        if source_manifest_path.is_file():
            source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            runtime_dlls = [
                str(runtime_dll).strip()
                for runtime_dll in source_manifest.get("windows_runtime", {}).get(
                    "dlls", []
                )
                if str(runtime_dll).strip()
            ]

        if with_runtime_dlls:
            if not runtime_dlls:
                raise ConanException(
                    "Expected source-manifest.json to declare bundled windows_runtime DLLs."
                )

            runtime_notice_packages = list(
                source_manifest.get("windows_runtime", {}).get("packages", [])
            )
            if not runtime_notice_packages:
                raise ConanException(
                    "Expected source-manifest.json to declare packaged notice files for the bundled windows_runtime DLLs."
                )

            executable_directories = sorted(
                {executable_path.parent for executable_path in package_root.rglob("*.exe")},
                key=lambda path: str(path).lower(),
            )
            missing_runtime_dlls: list[str] = []
            for executable_directory in executable_directories:
                missing_in_directory = [
                    runtime_dll
                    for runtime_dll in runtime_dlls
                    if not (executable_directory / runtime_dll).is_file()
                ]
                if missing_in_directory:
                    relative_directory = (
                        "."
                        if executable_directory == package_root
                        else str(executable_directory.relative_to(package_root))
                    )
                    missing_runtime_dlls.append(
                        f"{relative_directory}: {', '.join(missing_in_directory)}"
                    )

            if missing_runtime_dlls:
                raise ConanException(
                    "Expected each packaged executable directory to contain the bundled runtime DLLs: "
                    + "; ".join(missing_runtime_dlls)
                )

            runtime_notice_dlls = sorted(
                {
                    str(runtime_dll).strip()
                    for package in runtime_notice_packages
                    for runtime_dll in package.get("dlls", [])
                    if str(runtime_dll).strip()
                }
            )
            if runtime_notice_dlls != sorted(runtime_dlls):
                raise ConanException(
                    "Expected the runtime notice package metadata to cover the same DLL set declared in source-manifest.json."
                )

            missing_notice_files = sorted(
                {
                    str(notice_file).strip()
                    for package in runtime_notice_packages
                    for notice_file in package.get("notice_files", [])
                    if str(notice_file).strip()
                    and not (package_root / Path(str(notice_file))).is_file()
                }
            )
            if missing_notice_files:
                raise ConanException(
                    "Expected each declared runtime notice file to exist in the packaged bundle: "
                    + ", ".join(missing_notice_files)
                )

        if with_tray and with_packaging_support:
            tray_third_party_binary = package_root / "System.ServiceProcess.ServiceController.dll"
            tray_notice_packages = list(
                source_manifest.get("tray", {}).get("third_party_packages", [])
            )
            if tray_third_party_binary.is_file() and not tray_notice_packages:
                raise ConanException(
                    "Expected source-manifest.json to declare third-party tray package notices."
                )

            missing_tray_notice_files = sorted(
                {
                    str(notice_file).strip()
                    for package in tray_notice_packages
                    for notice_file in package.get("notice_files", [])
                    if str(notice_file).strip()
                    and not (package_root / Path(str(notice_file))).is_file()
                }
            )
            if missing_tray_notice_files:
                raise ConanException(
                    "Expected each declared tray-package notice file to exist in the packaged bundle: "
                    + ", ".join(missing_tray_notice_files)
                )

        self.run(f'"{squid_executable}" -v', env="conanrun")

        security_file_certgen = package_root / "libexec" / "security_file_certgen.exe"
        if security_file_certgen.is_file():
            self.run(f'"{security_file_certgen}" -h', env="conanrun")

