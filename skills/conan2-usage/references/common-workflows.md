# Conan 2 common workflows

## Bootstrap a consumer project

```bash
conan profile detect --force
conan install . --output-folder=build --build=missing
```

Use the detected profile only as a starting point. For CI and shared team
workflows, replace it with explicit checked-in profiles.

## Build a CMake project

```bash
conan install . --output-folder=build --build=missing
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=build/conan_toolchain.cmake
cmake --build build
```

If Conan generated CMake presets and the project supports them, `cmake --preset`
is usually cleaner than passing the toolchain file manually.

## Use a build tool from Conan

```ini
[tool_requires]
cmake/3.31.6
```

```bash
conan install . --output-folder=build --build=missing
cd build
source conanbuild.sh
cmake --version
```

PowerShell users should prefer profile or command configuration for
`tools.env.virtualenv:powershell=pwsh` so Conan emits `.ps1` activation files.

## Switch configuration

```bash
conan install . --output-folder=build --build=missing -s build_type=Debug
conan install . --output-folder=build --build=missing -o "*:shared=True"
```

If shared libraries are selected, activate `conanrun.*` before executing the
built program.

## Cross-build with host/build profiles

```bash
conan install . --build=missing -pr:b=default -pr:h=profiles/raspberry
```

Use `[buildenv]` in the host profile to point to cross-compilers when needed.

## Version ranges and updates

```python
def requirements(self):
    self.requires("zlib/[~1.3]")
```

```bash
conan install . --update
```

Ranges are useful only when the project explicitly wants automatic upgrades
within a bounded compatibility window.

## Lockfiles for reproducibility

```bash
conan lock create .
conan install . --lockfile=conan.lock
```

Use explicit lockfile arguments in CI even if Conan can auto-discover a nearby
`conan.lock`.

## Upload and consume from a remote

```bash
conan remote list
conan upload hello -r=my_remote
conan remove hello -c
conan install --requires=hello/1.0 -r=my_remote
```

Uploads to protected remotes should normally happen in CI, not from developer
machines.
