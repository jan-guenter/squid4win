---
name: conan2-package-creation
description: Conan 2 package-authoring skill for creating recipes, modeling binary compatibility, testing packages, using editables, and publishing packages safely.
---

# Conan 2 package creation

Guide agents through authoring Conan 2 packages: bootstrapping with `conan new`,
writing robust recipes, handling sources, shaping package IDs, testing with
`test_package`, iterating locally, and publishing to remotes.

## When to use

- "Create a Conan 2 package for this library or tool"
- "Write or refactor a `conanfile.py`"
- "Add `test_package` coverage"
- "Model options, settings, and package IDs correctly"
- "Package headers, libraries, tools, or prebuilt artifacts"
- "Use editable packages while developing producer and consumer together"
- "Upload or promote internally published Conan packages"

## Instructions

1. Bootstrap from a Conan 2 template when possible.
   - Start with `conan new` instead of writing a recipe from scratch unless the
     project already has a partial recipe.
   - For CMake libraries, `conan new cmake_lib -d name=<name> -d version=<ver>`
     is the standard tutorial starting point.
   - Preserve plain build-system files; do not inject Conan-specific logic into
     `CMakeLists.txt` unless the project genuinely needs it.

2. Fill in recipe metadata and package identity deliberately.
   - Set `name`, `version`, license, description, URL, and topics.
   - Keep package names lowercase and Conan-friendly.
   - If the package does not expose a `shared` option, define an explicit
     `package_type` when helpful so consumers understand the artifact kind.

3. Model settings and options before writing build logic.
   - Use `settings` for platform/compiler/build configuration inputs.
   - Use `options` for package-level toggles like `shared`, `fPIC`, or feature
     flags.
   - Use `config_options()` to delete options that are invalid before they take
     a value, for example `fPIC` on Windows.
   - Use `configure()` to remove irrelevant options or settings from the final
     binary model, such as `fPIC` when `shared=True`.
   - For C libraries, remove `compiler.cppstd` and `compiler.libcxx` if they do
     not affect the binary, or use `languages = "C"` where appropriate.
   - For header-only libraries, use `package_id()` with `self.info.clear()`.

4. Define `layout()` early and keep it accurate.
   - Prefer `cmake_layout(self)` for conventional CMake projects.
   - If editables or a nonstandard tree matter, define `self.folders.source`,
     `self.folders.build`, and `self.folders.generators` explicitly.
   - For editable packages, also define `self.cpp.source` and `self.cpp.build`
     so consumers can find headers and binaries in the working tree.

5. Treat sources as immutable.
   - Use `exports_sources` only when the source files live beside the recipe.
   - In `source()`, pin immutable tags or commits and use checksums for
     downloaded archives.
   - Do not use moving branches, mutable archives, or HEAD in production
     recipes.
   - Prefer `conandata.yml` to store version-specific URLs and hashes.

6. Add dependencies with the correct trait.
   - Use `self.requires()` for normal libraries.
   - Use `self.tool_requires()` for executable tools.
   - Use `self.test_requires()` for test frameworks and package-only test
     helpers.
   - Use `validate()` to reject unsupported compiler versions, standards,
     architectures, or dependency combinations.
   - Use `transitive_headers=True` only when your public headers actually expose
     another dependency's headers.

7. Keep `generate()`, `build()`, and `package()` separated by responsibility.
   - `generate()` prepares the build: toolchains, presets, copied resources,
     configuration values, and environment files.
   - `build()` should stay small and mostly call the build helper plus any
     package-level tests.
   - Patch in `build()` only when the patch is configuration-specific and cannot
     live in `source()`.
   - `package()` should prefer `cmake.install()` if the project already installs
     correctly; otherwise use targeted `copy()` calls.
   - Always package the license file.
   - Normalize or clean symlinks when the package contents require it.

8. Export accurate consumer metadata in `package_info()`.
   - Set `self.cpp_info.libs` for libraries consumers must link.
   - Use `set_property()` for generator-specific names like
     `cmake_target_name`.
   - Use `buildenv_info`, `runenv_info`, and `conf_info` only when consumers
     genuinely need those values.
   - Use components when a single package provides multiple libraries.

9. Keep `test_package` minimal and package-focused.
   - `test_package` proves the package can be consumed, not that the library is
     functionally correct in depth.
   - Use `self.tested_reference_str` in the test package recipe.
   - Build a tiny example consumer, then run it from `test()` with `can_run()`
     and `env="conanrun"`.
   - Put real unit and functional tests in the packaged project's normal test
     flow, usually inside `build()`.

10. Use the local development flow when iterating on recipes.
    - Start with `conan source`, then `conan install`, then `conan build`.
    - Use `conan export-pkg` when you want to package locally built artifacts
      into the cache without a full `conan create`.
    - Use `conan editable add` when producer and consumer must evolve together.
    - If multiple editables are involved, `conan build <consumer> --build=editable`
      can build them in order.
    - Do not upload packages built against editable upstreams without recreating
      them against released or in-cache dependencies.

11. Publish through controlled remotes and promotions.
    - Validate locally with `conan create` before upload.
    - Use `conan upload <ref> -r=<remote>` for the target remote.
    - Protected remotes should generally be writable only from CI.
    - Promote immutable packages between repositories to represent stages such as
      testing and release; do not use `user/channel` for that purpose.

12. Avoid forbidden and brittle patterns.
    - Never call Conan from inside a recipe, hook, or build script that Conan is
      already executing.
    - Never mutate settings or conf values inside recipes.
    - Never modify Conan cache contents manually.
    - Never mutate packaged artifacts from `package_info()` or `package_id()`.

## Authoring examples

### Bootstrap a library recipe

```bash
conan new cmake_lib -d name=hello -d version=1.0
conan create .
```

### Minimal CMake recipe

```python
from conan import ConanFile
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout


class HelloRecipe(ConanFile):
    name = "hello"
    version = "1.0"
    settings = "os", "compiler", "build_type", "arch"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = {"shared": False, "fPIC": True}
    exports_sources = "CMakeLists.txt", "src/*", "include/*"

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def layout(self):
        cmake_layout(self)

    def generate(self):
        CMakeDeps(self).generate()
        CMakeToolchain(self).generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.install()

    def package_info(self):
        self.cpp_info.libs = ["hello"]
```

### Source retrieval with `conandata.yml`

```yaml
sources:
  "1.0":
    url: "https://example.com/libhello-1.0.tar.gz"
    sha256: "<sha256>"
    strip_root: true
```

```python
from conan.tools.files import get


def source(self):
    get(self, **self.conan_data["sources"][self.version])
```

### Minimal `test_package`

```python
import os

from conan import ConanFile
from conan.tools.build import can_run
from conan.tools.cmake import CMake, cmake_layout


class HelloTestConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeDeps", "CMakeToolchain"

    def requirements(self):
        self.requires(self.tested_reference_str)

    def layout(self):
        cmake_layout(self)

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def test(self):
        if can_run(self):
            cmd = os.path.join(self.cpp.build.bindir, "example")
            self.run(cmd, env="conanrun")
```

For more snippets and local-dev commands, see
[`references/recipe-patterns.md`](references/recipe-patterns.md).

## Conan 2 package-authoring best practices

- Prefer `conan new` templates over hand-written boilerplate.
- Prepare the build in `generate()` and keep `build()` small.
- Keep sources immutable and versioned.
- Package licenses consistently.
- Keep `test_package` tiny and package-focused.
- Use editables for local producer/consumer iteration, not as a publishing
  shortcut.
- Publish through CI-controlled remotes and repository promotion.
- Never modify the Conan cache manually or invoke Conan recursively from a
  recipe.

## Related skills

- Use `conan2-usage` when the main task is consuming existing Conan packages,
  managing remotes, or improving reproducibility in a consumer project.
- Use `conan-vcpkg` when the user is still choosing between package managers.
