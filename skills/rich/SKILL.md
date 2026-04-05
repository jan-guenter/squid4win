---
name: rich
description: Use Rich for readable terminal output, tables, status, logging, JSON, and other renderables without over-styling.
skill_api_version: 1
---

# Rich

Use this skill when building or reviewing Python terminal output that
should be more readable than plain `print()` while still staying practical
on real terminals.

## Use this skill for

- creating a shared `Console` for an application
- choosing between plain rich printing, tables, JSON, logs, and status
  output
- readable debugging with `log()`, `inspect()`, and pretty-printed data
- width, overflow, justification, and color-system decisions
- terminal output that needs to work across Linux, macOS, and Windows

## Do not use this skill for

- full-screen TUIs that should really be built with Textual or another TUI
  framework
- hardcoding a color system above what the terminal supports
- styling every line when plain output would be clearer

## Working method

1. Start with one `Console`.
   - Most applications want a single shared `Console` instance.
   - Create it once at module or top-level object scope and reuse it.
2. Pick the simplest renderable that matches the job.
   - Use `Console.print()` for everyday output and light markup.
   - Use tables for structured comparisons.
   - Use `status()` while work is in progress.
   - Use `log()`, `inspect()`, or `print_json()` for debugging and
     diagnostics.
   - Use `out()` when you explicitly want low-level output without Rich's
     wrapping or markup behavior.
3. Respect terminal capabilities.
   - Rich auto-detects size, encoding, terminal status, and color system.
   - Only override `color_system` when you have a specific reason.
   - Remember that legacy Windows terminals are more limited than modern
     Windows Terminal.
4. Keep output readable.
   - Prefer Rich renderables over manual spacing.
   - Use `justify=` and `overflow=` intentionally, not by habit.
   - Use markup to clarify structure, not to turn everything into a demo.
5. Treat Rich as both UI and debugging infrastructure.
   - `log_locals=True` is useful for short-lived debugging.
   - `print_json()` and `inspect()` are often faster than writing custom
     dump helpers.

## Practical examples

### Shared console module

```python
from rich.console import Console

console = Console()
```

### Printing a table

```python
from rich.console import Console
from rich.table import Table

console = Console()

table = Table(show_header=True, header_style="bold magenta")
table.add_column("Name")
table.add_column("Status")
table.add_row("build", "ok")
table.add_row("tests", "running")

console.print(table)
```

### Status around work

```python
from rich.console import Console

console = Console()

with console.status("Working..."):
    do_work()
```

### Debugging helpers

```python
from rich import inspect
from rich.console import Console

console = Console()
console.log("Loaded configuration", log_locals=True)
inspect(config, methods=True)
console.print_json('{"status": "ok"}')
```

## Evaluation guidance

When refining this skill or reviewing advice produced with it:

- verify that the chosen Rich primitive matches the output problem instead
  of showing off every feature at once
- prefer examples built around a shared `Console` instance unless there is
  a good reason to construct one ad hoc
- check that readability survives narrow widths, redirected output, or
  lower terminal capability when those cases matter
- treat hardcoded color assumptions and excessive markup noise as failures

## Sources

- Rich:
  - [Introduction](https://rich.readthedocs.io/en/stable/introduction.html)
  - [Console](https://rich.readthedocs.io/en/stable/console.html)
  - [README](https://github.com/Textualize/rich/blob/master/README.md)
