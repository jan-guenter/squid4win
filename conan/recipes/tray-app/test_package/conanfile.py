from __future__ import annotations

from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException


class Squid4WinTrayTestPackage(ConanFile):
    settings = "os", "arch", "build_type"
    test_type = "explicit"

    def requirements(self) -> None:
        self.requires(self.tested_reference_str)

    def test(self) -> None:
        package_name = self.tested_reference_str.split("/", 1)[0]
        dependency = self.dependencies[package_name]
        tray_executable = Path(dependency.package_folder) / "bin" / "Squid4Win.Tray.exe"

        if not tray_executable.is_file():
            raise ConanException(
                f"Expected the tray executable at {tray_executable}."
            )

