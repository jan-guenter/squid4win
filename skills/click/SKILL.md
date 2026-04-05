---
name: click
description: Build Python CLIs with Click using commands, groups, parameters, shell completion, testing, and packaging-aware guidance.
skill_api_version: 1
---

# Click

Use this skill when building or reviewing a Python CLI that uses Click
directly rather than a higher-level wrapper.

## Use this skill for

- `@click.command()` and `@click.group()` design
- options, arguments, grouped subcommands, and late command registration
- robust user-facing output with `click.echo()`
- shell completion and custom completion hooks
- testing Click apps with `click.testing.CliRunner`

## Do not use this skill for

- Typer-first code unless you explicitly need Click-level behavior
- non-Python CLI work
- completion guidance that ignores entry-point packaging requirements

## Working method

1. Start with decorators and a real entry point.
   - Use `@click.command()` for a leaf command and `@click.group()` for a
     command tree.
   - Prefer installed console entry points once the tool is distributable;
     Click's docs recommend entry points for Windows wrappers and shell
     completion.
2. Use Click primitives for CLI UX.
   - Prefer `click.echo()` for user-facing text because it handles Unicode
     and styles more robustly than raw `print()`.
   - Use `@click.option()` and `@click.argument()` instead of manual
     `argv` parsing.
3. Organize growth deliberately.
   - Use `@group.command()` for nearby subcommands.
   - Use `group.add_command()` when commands live in separate modules or
     are registered later.
4. Treat completion as a packaged feature.
   - Built-in completion support covers Bash 4.4+, Zsh, and Fish.
   - Completion works when the executable is installed and invoked through
     an entry point, not when running `python script.py`.
   - Use `shell_complete=` or `ParamType.shell_complete()` for custom
     value completion.
5. Test with `CliRunner`.
   - Use `runner.invoke()` for exit codes, output, and exceptions.
   - Use `runner.isolated_filesystem()` for file-based behavior.
   - Use `input=` for prompts.
   - Remember that Click's testing helpers change interpreter state and are
     meant for tests, not production code.

## Practical examples

### Command group with options and arguments

```python
import click

@click.group()
def cli():
    pass

@cli.command()
@click.option("--count", default=1, help="Number of greetings.")
@click.argument("name")
def hello(count, name):
    for _ in range(count):
        click.echo(f"Hello {name}!")

if __name__ == "__main__":
    cli()
```

### Testing a Click command

```python
from click.testing import CliRunner

from .hello import hello

def test_hello_world():
    runner = CliRunner()
    result = runner.invoke(hello, ["Peter"])
    assert result.exit_code == 0
    assert result.output == "Hello Peter!\n"
```

### Isolated filesystem testing

```python
from click.testing import CliRunner

from .cat import cat

def test_cat():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("hello.txt", "w", encoding="utf-8") as handle:
            handle.write("Hello World!")

        result = runner.invoke(cat, ["hello.txt"])
        assert result.exit_code == 0
        assert result.output == "Hello World!\n"
```

### Custom shell completion callback

```python
import os

import click

def complete_env_vars(ctx, param, incomplete):
    return [name for name in os.environ if name.startswith(incomplete)]

@click.command()
@click.argument("name", shell_complete=complete_env_vars)
def show(name):
    click.echo(os.environ[name])
```

## Evaluation guidance

When refining this skill or reviewing advice produced with it:

- verify that examples use Click primitives instead of manual argument
  parsing
- treat `print()` as a conscious exception, not the default recommendation,
  when `click.echo()` would be more robust
- ensure shell-completion guidance keeps the entry-point requirement
- prefer `CliRunner`-based tests for normal CLI behavior
- include at least one grouped-command prompt and one prompt-driven test
  case when iterating on the skill

## Sources

- Click:
  - [Home](https://click.palletsprojects.com/en/stable/)
  - [Quickstart](https://click.palletsprojects.com/en/stable/quickstart/)
  - [Testing Click Applications](https://click.palletsprojects.com/en/stable/testing/)
  - [Shell Completion](https://click.palletsprojects.com/en/stable/shell-completion/)
