---
name: shellingham
description: Detect the surrounding shell safely for completion or shell-specific guidance, with robust fallbacks and user-friendly failure handling.
skill_api_version: 1
---

# Shellingham

Use this skill when a Python CLI needs to know which shell launched it,
usually to install completion or to choose shell-specific instructions.

## Use this skill for

- calling `shellingham.detect_shell()` and handling the returned tuple
- graceful fallback behavior when no shell can be detected
- choosing between POSIX and Windows default-shell behavior
- CLI UX that needs shell-specific completion or setup guidance

## Do not use this skill for

- making core CLI behavior depend on shell detection
- assuming every process is launched from an interactive shell
- replacing simple `SHELL` or `COMSPEC` defaults when detection is not
  actually needed

## Working method

1. Treat detection as best-effort.
   - Shellingham is useful for better UX, not for blocking the main task.
2. Call `shellingham.detect_shell()` and unpack the `(name, executable)`
   tuple.
   - The shell name is always lowercased.
   - On Windows, the shell name is the executable stem without the file
     extension.
3. Catch `ShellDetectionFailure`.
   - The user is not necessarily running inside a shell.
   - For POSIX interactive defaults, prefer the `SHELL` environment
     variable.
   - For portable script execution on POSIX, `sh` or `/bin/sh` is a safer
     baseline.
   - On Windows, `COMSPEC` is the portable command-prompt fallback.
4. Keep UX resilient.
   - Do not surface detection failure to end users unless the failure is
     truly actionable.
   - Use detection to pick instructions, not to decide whether your app is
     allowed to continue.

## Practical examples

### Best-effort shell detection with fallback

```python
import os
from pathlib import Path

import shellingham

def detect_shell_for_completion():
    try:
        return shellingham.detect_shell()
    except shellingham.ShellDetectionFailure:
        if os.name == "posix":
            executable = os.environ.get("SHELL", "/bin/sh")
            return Path(executable).name.lower(), executable
        if os.name == "nt":
            executable = os.environ.get("COMSPEC", "cmd.exe")
            return Path(executable).stem.lower(), executable
        raise
```

### Choosing shell-specific instructions

```python
shell_name, executable = detect_shell_for_completion()

if shell_name in {"bash", "zsh", "fish", "powershell", "pwsh"}:
    print(f"Install completion instructions for {shell_name}")
else:
    print(f"Use a generic fallback for {executable}")
```

## Evaluation guidance

When refining this skill or reviewing advice produced with it:

- verify that the main workflow still works when detection fails
- treat unhandled `ShellDetectionFailure` in ordinary UX flows as a bug
- verify that Windows advice uses `COMSPEC` and does not assume `.exe`
  remains in the returned shell name
- include at least one non-interactive or detection-failure scenario when
  iterating on the skill

## Sources

- Shellingham:
  - [README.rst](https://github.com/sarugaku/shellingham/blob/main/README.rst)
