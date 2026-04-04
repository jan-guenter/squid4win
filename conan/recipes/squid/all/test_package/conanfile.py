from __future__ import annotations

from pathlib import Path

from conan import ConanFile
from conan.errors import ConanException


class SquidTestPackage(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    test_type = "explicit"

    def requirements(self) -> None:
        self.requires(self.tested_reference_str)

    def test(self) -> None:
        package_name = self.tested_reference_str.split("/", 1)[0]
        dependency = self.dependencies[package_name]
        package_root = Path(dependency.package_folder)

        self._require_file(self._require_squid_executable(package_root))
        self._require_file(package_root / "licenses" / "COPYING")
        self._require_absent(package_root / "THIRD-PARTY-NOTICES.txt")
        self._require_absent(package_root / "licenses" / "source-manifest.json")
        self._require_absent(package_root / "installer")
        self._require_absent(package_root / "Squid4Win.Tray.exe")

    @staticmethod
    def _require_squid_executable(package_root: Path) -> Path:
        squid_candidates = (
            package_root / "sbin" / "squid.exe",
            package_root / "sbin" / "squid",
            package_root / "bin" / "squid.exe",
            package_root / "bin" / "squid",
        )
        squid_executable = next(
            (candidate for candidate in squid_candidates if candidate.is_file()),
            None,
        )
        if squid_executable is None:
            raise ConanException(
                f"Expected a squid executable under {package_root}, but none was found."
            )

        return squid_executable

    @staticmethod
    def _require_file(path: Path) -> None:
        if not path.is_file():
            raise ConanException(f"Expected the packaged file at {path}.")

    @staticmethod
    def _require_absent(path: Path) -> None:
        if path.exists():
            raise ConanException(
                f"Did not expect the pure native Squid package to contain {path}."
            )
