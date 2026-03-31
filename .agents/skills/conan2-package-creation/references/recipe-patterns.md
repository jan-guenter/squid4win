# Conan 2 recipe patterns

## Bootstrap a new package

```bash
conan new cmake_lib -d name=hello -d version=1.0
```

Use the generated files as the starting point, then replace placeholder metadata
and tune settings, options, and package logic for the real project.

## `source()` with immutable inputs

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

Prefer immutable tags, commits, and checksummed archives. Avoid moving branches
and mutable source URLs.

## Conditional options and validation

```python
options = {"shared": [True, False], "fPIC": [True, False], "with_fmt": [True, False]}
default_options = {"shared": False, "fPIC": True, "with_fmt": True}


def config_options(self):
    if self.settings.os == "Windows":
        del self.options.fPIC


def configure(self):
    if self.options.shared:
        self.options.rm_safe("fPIC")


def validate(self):
    if self.options.with_fmt:
        check_min_cppstd(self, "11")
```

## `generate()` as the build-preparation step

```python
def generate(self):
    tc = CMakeToolchain(self)
    if self.options.with_fmt:
        tc.variables["WITH_FMT"] = True
    tc.generate()
    CMakeDeps(self).generate()
```

Keep recipe preparation here rather than in `build()`.

## `package()` patterns

### Prefer build-system install

```python
def package(self):
    cmake = CMake(self)
    cmake.install()
```

### Copy artifacts manually when needed

```python
def package(self):
    copy(self, "LICENSE", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
    copy(self, "*.h", src=os.path.join(self.source_folder, "include"), dst=os.path.join(self.package_folder, "include"))
    copy(self, "*.a", src=self.build_folder, dst=os.path.join(self.package_folder, "lib"), keep_path=False)
    copy(self, "*.lib", src=self.build_folder, dst=os.path.join(self.package_folder, "lib"), keep_path=False)
    copy(self, "*.dll", src=self.build_folder, dst=os.path.join(self.package_folder, "bin"), keep_path=False)
```

## `package_info()` basics

```python
def package_info(self):
    self.cpp_info.libs = ["hello"]
    self.cpp_info.set_property("cmake_target_name", "hello::hello")
```

Use components if the package exports multiple logical libraries.

## Minimal local iteration loop

```bash
conan source .
conan install .
conan build .
conan export-pkg .
```

Use this when recipe work would be too slow with repeated `conan create`.

## Editable workflow

```bash
conan editable add .
conan install . -s build_type=Release
cmake --preset conan-release
cmake --build --preset conan-release
```

Consumers can then resolve the package directly from the working tree.

If multiple editables are involved:

```bash
conan build consumer --build=editable
```
