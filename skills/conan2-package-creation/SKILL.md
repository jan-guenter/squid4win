---
name: conan2-package-creation
description: Guide Conan 2 package authoring for recipes, metadata, binary compatibility, test_package flows, editables, and publication.
skill_api_version: 1
---

# Conan 2 package creation

Use this skill when the task is about **authoring or refactoring** a Conan
2 recipe.

## Use this skill for

- creating a new `conanfile.py` recipe
- refactoring an existing Conan 2 recipe
- modeling settings, options, and package IDs correctly
- packaging libraries, tools, headers, or prebuilt artifacts
- adding or improving `test_package`
- using editables while developing producer and consumer together
- validating and publishing packages to remotes

## Do not use this skill for

- simple dependency consumption in an existing project; use `conan2-usage`
- general build-system integration work that is not primarily recipe
  authoring

## Working method

1. Bootstrap from Conan 2 templates when practical.
   - Start with `conan new` instead of hand-writing a recipe from scratch
     unless the project already has a partial recipe worth preserving.
   - Preserve the project's normal build-system files; do not inject Conan
     logic into them unless the project genuinely needs it.
2. Fill in recipe metadata deliberately.
   - Set `name`, `version`, license, description, URL, and topics.
   - Keep package names lowercase and Conan-friendly.
   - Use `package_type` when it helps communicate whether the recipe
     produces a library, application, header-only package, or tool.
3. Model settings and options before writing build logic.
   - Use `settings` for platform, compiler, architecture, and build type.
   - Use `options` for package-specific toggles such as `shared`, `fPIC`,
     or feature flags.
   - Use `config_options()` to remove invalid options before they take
     values.
   - Use `configure()` to remove irrelevant values from the final binary
     model.
   - For header-only libraries, use `package_id()` with
     `self.info.clear()`.
4. Define `layout()` early and keep it accurate.
   - Prefer `cmake_layout(self)` for conventional CMake projects.
   - For nonstandard trees or editable flows, define source, build, and
     generators folders explicitly.
   - When editables matter, also define the `self.cpp.source` and
     `self.cpp.build` locations consumers should use.
5. Treat sources as immutable.
   - Use `exports_sources` only when the relevant source files live beside
     the recipe.
   - In `source()`, pin immutable tags or commits and verify downloads with
     checksums.
   - Prefer `conandata.yml` for version-specific URLs, hashes, and patch
     data.
   - Do not use moving branches, mutable archives, or `HEAD` in production
     recipes.
6. Add dependencies with the correct trait.
   - Use `self.requires()` for libraries.
   - Use `self.tool_requires()` for executable build tools.
   - Use `self.test_requires()` for test frameworks or package-focused test
     helpers.
   - Use `validate()` to reject unsupported compiler versions,
     architectures, standards, or dependency combinations.
7. Keep `generate()`, `build()`, and `package()` separated by
   responsibility.
   - `generate()` prepares toolchains, presets, copied resources, and
     other generated build inputs.
   - `build()` should stay small and mostly delegate to the build helper.
   - `package()` should prefer the project's normal install flow when it
     exists, otherwise use targeted `copy()` calls.
   - Always package the license file.
8. Export accurate consumer metadata in `package_info()`.
   - Set `self.cpp_info.libs` for libraries that consumers must link.
   - Use `set_property()` for generator-specific names such as
     `cmake_target_name`.
   - Use components when one package provides multiple libraries.
   - Only expose build or run environment values when consumers genuinely
     need them.
9. Keep `test_package` small and package-focused.
   - `test_package` proves the package can be consumed; it is not the
     place for deep functional testing.
   - Use `self.tested_reference_str` in the test recipe.
   - Build a tiny example consumer and run it with `can_run()` plus
     `env="conanrun"`.
10. Use local development flows intentionally.
    - Use `conan source`, `conan install`, and `conan build` while
      iterating on a recipe.
    - Use `conan export-pkg` when you want to package locally built
      artifacts into the cache.
    - Use `conan editable add` when producer and consumer must evolve
      together.
    - Do not publish artifacts built against editable upstreams without
      recreating them against released or cached dependencies.
11. Publish through controlled remotes and promotions.
    - Validate locally with `conan create` before upload.
    - Use `conan upload <ref> -r=<remote>` for the destination remote.
    - Protected remotes should generally be writable only from CI.
    - Represent maturity through repository promotion, not through
      `user/channel`.
12. Avoid brittle patterns.
    - Never call Conan from inside a recipe or from build logic Conan is
      already executing.
    - Never mutate settings or configuration values inside recipes.
    - Never modify Conan cache contents manually.
    - Never mutate packaged artifacts from `package_info()` or
      `package_id()`.

## Practical examples

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

## Evaluation guidance

When refining this skill or reviewing advice produced with it:

- use at least one "new recipe" prompt and one "refactor existing recipe"
  prompt
- treat Conan 1 generators, deprecated Conan 1 idioms, or recursive Conan
  invocation as failures
- verify that settings, options, layout, and source immutability are
  decided before deep build logic appears
- verify that `test_package` stays package-focused and that
  `package_info()` describes consumer metadata instead of build-time logic

## Sources

- Conan 2 docs:
  - [Create your first package](https://docs.conan.io/2/tutorial/creating_packages/create_your_first_package.html)
  - [package_info()](https://docs.conan.io/2/reference/conanfile/methods/package_info.html)
