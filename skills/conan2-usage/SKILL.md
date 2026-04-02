---
name: conan2-usage
description: Guide Conan 2 consumer workflows for dependency installation, profiles, generators, remotes, lockfiles, and reproducible builds.
skill_api_version: 1
---

# Conan 2 usage

Use this skill when the task is about **consuming** packages with Conan 2 rather
than authoring a package recipe from scratch.

## Use this skill for

- adding dependencies to an existing project with Conan 2
- choosing between `conanfile.txt` and `conanfile.py` for a consumer
- configuring host and build profiles
- integrating Conan with CMake or another build system
- managing remotes, lockfiles, and reproducible installs
- troubleshooting missing binaries, graph drift, or cross-build confusion

## Do not use this skill for

- creating or publishing a new Conan package recipe from scratch; use
  `conan2-package-creation` instead
- deciding between Conan and a different package manager; use a comparison skill
  if one is available

## Working method

1. Inspect the current consumer state first.
   - Read the existing Conan manifest, profiles, lockfiles, build scripts, and
     CI before changing anything.
   - Determine whether the project already follows Conan 2 conventions.
   - Do not mix Conan 1 idioms into a Conan 2 project.

2. Choose the right manifest shape.
   - Use `conanfile.txt` for simple consumers with fixed requirements,
     generators, and no custom logic.
   - Use `conanfile.py` when you need conditional requirements, custom layout,
     validation, custom `generate()` logic, or build-system orchestration.

3. Treat profiles as the source of truth for real builds.
   - `conan profile detect --force` is acceptable for first-run local bootstrap.
   - For CI, release, and team workflows, prefer explicit checked-in profiles or
     configuration installed through `conan config install`.
   - For cross-building, always reason in terms of `--profile:build` and
     `--profile:host`.
   - If concurrent jobs share a machine, isolate `CONAN_HOME` per job.

4. Prefer the explicit Conan-plus-build-system flow.
   - Run `conan install ...` before the native build tool.
   - For CMake, prefer `CMakeToolchain` plus `CMakeDeps` unless the project has
     a deliberate reason to use another integration.
   - Avoid implicit `cmake-conan` flows unless the project explicitly needs that
     IDE-driven behavior.

5. Use dependency traits correctly.
   - Use normal requirements for libraries the consumer links against.
   - Use `tool_requires` only for executable build tools such as `cmake`,
     `ninja`, code generators, or cross toolchains.
   - Use generated build and run environments when tools or shared libraries need
     activation.

6. Model settings, options, and environments deliberately.
   - Settings describe platform, compiler, architecture, and build type.
   - Options describe package-specific toggles such as `shared=True`.
   - These values affect package IDs and binary resolution.
   - When consuming shared libraries, activate the generated run environment so
     executables can resolve dynamic libraries at runtime.

7. Use version ranges intentionally.
   - Prefer fixed versions when the project wants controlled upgrades.
   - Use version ranges only when the consumer intentionally wants newer
     compatible versions without editing the manifest.
   - If ranges are in use and newer remote versions should be preferred over the
     cache, use `--update`.

8. Use lockfiles for reproducibility.
   - Capture lockfiles for CI, release, or team-wide consistency.
   - Be explicit with `--lockfile=...` in automation.
   - Use `--lockfile-partial` only when intentionally extending an incomplete
     lock.

9. Manage remotes conservatively.
   - Inspect the current remote configuration before adding or changing remotes.
   - Prefer organization-controlled remotes for production workflows.
   - Protected repositories should generally be writable by CI rather than by
     individual developer workstations.

10. Troubleshoot through Conan's binary model.
    - Missing binary: inspect settings, options, profiles, and package ID inputs
      before reaching for `--build=missing`.
    - Wrong runtime search path: activate the generated run environment.
    - Cross-build confusion: verify build and host profiles.
    - Graph drift: inspect version ranges, revisions, remotes, `--update`, and
      lockfile usage.

## Common flows

### Simple CMake consumer

```ini
[requires]
zlib/1.3.1

[generators]
CMakeDeps
CMakeToolchain
```

```bash
conan profile detect --force
conan install . --output-folder=build --build=missing
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=build/conan_toolchain.cmake
cmake --build build
```

### Consumer with logic in `conanfile.py`

```python
from conan import ConanFile
from conan.tools.cmake import cmake_layout


class AppConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeToolchain", "CMakeDeps"

    def requirements(self):
        self.requires("zlib/1.3.1")

    def build_requirements(self):
        self.tool_requires("cmake/3.31.6")

    def layout(self):
        cmake_layout(self)
```

### Cross-build install

```bash
conan install . --build=missing -pr:b=default -pr:h=profiles/raspberry
```

### Lockfile workflow

```bash
conan lock create .
conan install . --lockfile=conan.lock
```

### Remote workflow

```bash
conan remote list
conan upload hello -r=my_remote
conan install --requires=hello/1.0 -r=my_remote
```

## Best practices

- Keep consumer logic as small and explicit as possible.
- Use checked-in profiles and lockfiles for repeatable automation.
- Isolate `CONAN_HOME` for parallel jobs because the Conan cache is not
  concurrency-safe.
- Do not abuse `tool_requires` for normal libraries.
- Treat `override=True` and `force=True` as deliberate conflict workarounds, not
  as the default versioning model.
- Never invoke Conan recursively from a recipe or build script that Conan is
  already driving.
- Never edit Conan cache contents manually.
