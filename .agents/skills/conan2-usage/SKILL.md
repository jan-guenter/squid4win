---
name: conan2-usage
description: Conan 2 consumer workflows for installing dependencies, managing profiles, integrating with CMake, using remotes, and keeping builds reproducible.
---

# Conan 2 usage

Guide agents through day-to-day Conan 2 usage: consuming packages, choosing
`conanfile.txt` vs `conanfile.py`, configuring profiles, integrating with
CMake, using remotes, and keeping dependency graphs reproducible.

## When to use

- "Add a dependency with Conan 2"
- "Set up Conan 2 for this CMake project"
- "Use tool packages like CMake or Ninja with Conan"
- "Cross-compile with Conan host/build profiles"
- "Lock dependencies for CI or releases"
- "Upload or consume packages from a remote"
- "Resolve Conan version conflicts or missing binaries"

## Instructions

1. Inspect the existing Conan and build-system state first.
   - Read `conanfile.py`, `conanfile.txt`, profiles, lockfiles, build scripts,
     and CI before changing anything.
   - Identify whether the project already uses Conan 2 conventions and whether
     it builds with CMake, Meson, Autotools, Visual Studio, or another system.
   - Do not mix Conan 1 idioms into a Conan 2 project.

2. Choose the right manifest shape.
   - Use `conanfile.txt` only for simple consumers with fixed requirements and
     generators.
   - Use `conanfile.py` when you need conditional requirements, custom layout,
     validation, custom `generate()` logic, resource copying, or a recipe-local
     `build()` method.

3. Treat profiles as the source of truth for real builds.
   - `conan profile detect --force` is acceptable for first-run local bootstrap.
   - In CI, production, and team workflows, prefer explicit profiles or
     `conan config install`.
   - For cross-building, always reason in terms of `--profile:build` and
     `--profile:host`.
   - If concurrent jobs run on the same machine, isolate `CONAN_HOME` per job.

4. Prefer the explicit Conan + build-system flow.
   - For CMake, run `conan install ...` first, then `cmake --preset ...` or
     `cmake -DCMAKE_TOOLCHAIN_FILE=...`.
   - Prefer `CMakeToolchain` plus `CMakeDeps` for the standard tutorial flow.
   - `CMakeConfigDeps` is a newer alternative when the project can adopt it.
   - Avoid implicit `cmake-conan` flows unless the project explicitly needs
     that IDE integration.

5. Use `tool_requires` only for executable build tools.
   - Good fits: `cmake`, `ninja`, code generators, cross toolchains.
   - Do not use `tool_requires` for normal libraries.
   - If the tool package must be used directly, activate the generated build
     environment (`conanbuild.*`) before invoking it.
   - For PowerShell-heavy projects, configure
     `tools.env.virtualenv:powershell=<powershell.exe|pwsh>` in the profile or
     pass it on the command line so Conan emits `.ps1` activation scripts.

6. Model settings, options, and runtime environment correctly.
   - Settings are platform/compiler/build configuration inputs.
   - Options are package-specific toggles such as `shared=True`.
   - These values influence the package ID and therefore binary resolution.
   - When consuming shared libraries, use the generated run environment
     (`conanrun.*`) so executables can resolve DLLs and shared objects.

7. Use version ranges intentionally, not casually.
   - Prefer fixed versions when the project wants predictable upgrades.
   - Use version ranges only when the consumer explicitly wants newer matching
     versions without editing the manifest.
   - If ranges are in use and the project should prefer newer remote versions
     over cache results, use `--update`.
   - Pre-releases should stay opt-in.

8. Use lockfiles for reproducibility.
   - Capture lockfiles for CI, releases, and team-wide consistency.
   - Be explicit with `--lockfile=...` in automation, even if Conan can pick up
     a nearby `conan.lock` automatically.
   - Use `--lockfile-partial` only when intentionally extending a partially
     covered graph.
   - If lockfiles evolve, do it in a controlled way and keep changes reviewable.

9. Manage remotes and promotions conservatively.
   - Inspect `conan remote list` before adding or changing remotes.
   - For production usage, prefer organization-controlled remotes instead of
     unconstrained direct dependence on ConanCenter.
   - Protected repositories should be uploadable by CI, not by individual
     developer workstations.
   - Model maturity with repository promotion, not with `user/channel`.

10. Resolve conflicts with the least risky mechanism.
    - Prefer aligning upstream requirements first.
    - Treat `override=True` and `force=True` as temporary conflict workarounds,
      not as the long-term versioning model.
    - Remember: `force=True` creates a direct dependency, while
      `override=True` only rewrites an already-transitive one.

11. Troubleshoot by following Conan's binary model.
    - Missing binary: inspect settings, options, profiles, and package ID
      inputs before reaching for `--build=missing`.
    - Wrong runtime search path: activate `conanrun.*`.
    - Cross-build confusion: verify host/build profiles and `[buildenv]`.
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

For more command patterns, see
[`references/common-workflows.md`](references/common-workflows.md).

## Conan 2 best practices

- Keep `build()` simple; prepare the build in `generate()`.
- Use explicit, checked-in profiles for CI and production.
- Isolate `CONAN_HOME` for parallel jobs because the Conan cache is not
  concurrency-safe.
- Do not abuse `tool_requires`.
- Avoid using `force` and `override` as a general versioning strategy.
- Avoid using `user/channel` to represent maturity or environments.
- Never call Conan from inside recipes or build scripts already being driven by
  Conan.
- Never edit cache contents manually.
- Use immutable sources and reproducible lockfiles when builds matter.

## Related skills

- Use `conan-vcpkg` when the user is deciding between Conan and vcpkg or when a
  project mixes both ecosystems.
