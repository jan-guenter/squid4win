---
name: typer
description: Build Python CLIs with Typer using type hints, commands, options, testing, completion, and packaging-aware guidance.
skill_api_version: 1
---

# Typer

Use this skill when building or reviewing a Python CLI that should feel
like ordinary typed Python code while still getting Click-powered help,
completion, and UX.

## Use this skill for

- small single-command CLIs powered by `typer.run()`
- multi-command applications built with `typer.Typer()`
- translating Python type hints into CLI arguments and options
- prompts, help text, command grouping, and shell-completion guidance
- testing Typer apps with `typer.testing.CliRunner`

## Do not use this skill for

- non-Python CLI work
- Click-only code when the project deliberately wants the lower-level
  Click API
- completion instructions that ignore packaging or executable entry points

## Working method

1. Choose the app shape intentionally.
   - Use `typer.run(function)` for a very small single-command script.
   - Use `app = typer.Typer(...)` once the CLI has multiple commands or is
     likely to grow.
2. Let type hints define the CLI first.
   - Required parameters become arguments.
   - Parameters with defaults become options.
   - Boolean options naturally expose paired flags such as `--formal` and
     `--no-formal`.
3. Add Typer metadata only where it adds value.
   - Use `Annotated[..., typer.Option(...)]` or
     `Annotated[..., typer.Argument(...)]` when you need help text,
     prompts, defaults, validation, or richer parameter metadata.
   - Prefer the simplest plain type-hinted signature when metadata is not
     needed.
4. Keep help and command layout deliberate.
   - Command names default to the function names.
   - Command order in help follows declaration order.
   - `no_args_is_help=True` is useful when a blank invocation should show
     the help page instead of doing nothing.
5. Keep execution and packaging claims honest.
   - Single-command apps omit the command name in usage.
   - Multi-command apps require the command name explicitly.
   - Auto-completion works when users install the package entry point or
     when they run the app through the `typer` command.
6. Test the CLI like a CLI.
   - Use `typer.testing.CliRunner`.
   - Assert `exit_code`, `output`, and prompt behavior via `input=...`.
   - If the production module only uses `typer.run(main)`, you can still
     build a test-only `Typer()` app around that function.

## Practical examples

### Single-command script

```python
import typer

def main(name: str):
    print(f"Hello {name}")

if __name__ == "__main__":
    typer.run(main)
```

### Multi-command app

```python
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)

@app.command()
def hello(name: str):
    print(f"Hello {name}")

@app.command()
def goodbye(
    name: str,
    formal: Annotated[bool, typer.Option(help="Use a formal goodbye")] = False,
):
    if formal:
        print(f"Goodbye Ms. {name}. Have a good day.")
    else:
        print(f"Bye {name}!")

if __name__ == "__main__":
    app()
```

### Testing a Typer app

```python
from typer.testing import CliRunner

from .main import app

runner = CliRunner()

def test_hello():
    result = runner.invoke(app, ["hello", "Camila"])
    assert result.exit_code == 0
    assert "Hello Camila" in result.output
```

### Testing prompt input

```python
from typing import Annotated

import typer
from typer.testing import CliRunner

app = typer.Typer()

@app.command()
def subscribe(
    email: Annotated[str, typer.Option(prompt="Email address")],
):
    print(email)

runner = CliRunner()

def test_prompt():
    result = runner.invoke(app, ["subscribe"], input="camila@example.com\n")
    assert result.exit_code == 0
    assert "camila@example.com" in result.output
```

## Evaluation guidance

When refining this skill or reviewing advice produced with it:

- use at least one single-command prompt and one multi-command prompt
- verify that the guidance respects Typer's one-command versus many-command
  behavior
- prefer examples that a reader can run or test immediately
- treat completion claims that ignore installed entry points or the
  `typer` command as failures
- treat tests that skip `CliRunner` for ordinary CLI behavior as a warning
  sign

## Sources

- Typer:
  - [Home](https://typer.tiangolo.com/)
  - [Tutorial: Commands](https://typer.tiangolo.com/tutorial/commands/)
  - [Tutorial: Testing](https://typer.tiangolo.com/tutorial/testing/)
