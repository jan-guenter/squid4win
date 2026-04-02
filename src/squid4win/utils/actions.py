from __future__ import annotations

import html
import json
import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Final, Self
from uuid import uuid4

from squid4win.models import GitHubActionsContext

__all__ = [
    "GitHubAnnotationLevel",
    "GitHubStepSummary",
    "add_path",
    "annotation_level_from_logging",
    "append_path",
    "append_step_summary",
    "context",
    "debug",
    "end_group",
    "error",
    "export_variable",
    "format_annotation",
    "group",
    "info",
    "is_enabled",
    "issue_command",
    "notice",
    "render_command",
    "save_state",
    "set_output",
    "set_outputs",
    "set_secret",
    "start_group",
    "summary",
    "to_command_value",
    "warning",
]

_NEWLINE: Final[str] = "\n"

_context_cache: GitHubActionsContext | None = None


class GitHubAnnotationLevel(StrEnum):
    DEBUG = "debug"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


def context(*, refresh: bool = False) -> GitHubActionsContext:
    global _context_cache
    if refresh or _context_cache is None:
        _context_cache = GitHubActionsContext()
    return _context_cache


def is_enabled() -> bool:
    return context().enabled


def annotation_level_from_logging(level: int) -> GitHubAnnotationLevel | None:
    if level >= logging.ERROR:
        return GitHubAnnotationLevel.ERROR
    if level >= logging.WARNING:
        return GitHubAnnotationLevel.WARNING
    return None


def to_command_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _escape_command_message(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_command_property(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def render_command(
    command: str,
    message: object = "",
    *,
    properties: Mapping[str, object] | None = None,
) -> str:
    rendered_message = to_command_value(message)
    prefix = f"::{command}"
    if properties:
        rendered_properties = [
            f"{name}={_escape_command_property(to_command_value(value))}"
            for name, value in properties.items()
            if value is not None
        ]
        if rendered_properties:
            prefix = f"{prefix} {','.join(rendered_properties)}"

    return f"{prefix}::{_escape_command_message(rendered_message)}"


def format_annotation(
    level: GitHubAnnotationLevel,
    message: object,
    *,
    title: str | None = None,
    file: Path | str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    column: int | None = None,
    end_column: int | None = None,
    enabled: bool | None = None,
) -> str:
    rendered_message = to_command_value(message)
    if enabled is None:
        enabled = is_enabled()

    if not enabled:
        return rendered_message

    return render_command(
        level.value,
        rendered_message,
        properties=_annotation_properties(
            title=title,
            file=file,
            line=line,
            end_line=end_line,
            column=column,
            end_column=end_column,
        ),
    )


def issue_command(
    command: str,
    message: object = "",
    *,
    properties: Mapping[str, object] | None = None,
) -> None:
    if is_enabled():
        print(render_command(command, message, properties=properties), flush=True)
        return

    rendered_message = to_command_value(message)
    if rendered_message and command not in {"add-mask", "endgroup"}:
        print(rendered_message, flush=True)


def info(message: object) -> None:
    print(to_command_value(message), flush=True)


def debug(message: object) -> None:
    issue_command("debug", message)


def _annotation_properties(
    *,
    title: str | None = None,
    file: Path | str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    column: int | None = None,
    end_column: int | None = None,
) -> dict[str, object]:
    properties: dict[str, object] = {}
    if title is not None:
        properties["title"] = title
    if file is not None:
        properties["file"] = file
    if line is not None:
        properties["line"] = line
    if end_line is not None:
        properties["endLine"] = end_line
    if column is not None:
        properties["col"] = column
    if end_column is not None:
        properties["endColumn"] = end_column
    return properties


def notice(
    message: object,
    *,
    title: str | None = None,
    file: Path | str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    column: int | None = None,
    end_column: int | None = None,
) -> None:
    issue_command(
        GitHubAnnotationLevel.NOTICE.value,
        message,
        properties=_annotation_properties(
            title=title,
            file=file,
            line=line,
            end_line=end_line,
            column=column,
            end_column=end_column,
        ),
    )


def warning(
    message: object,
    *,
    title: str | None = None,
    file: Path | str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    column: int | None = None,
    end_column: int | None = None,
) -> None:
    issue_command(
        GitHubAnnotationLevel.WARNING.value,
        message,
        properties=_annotation_properties(
            title=title,
            file=file,
            line=line,
            end_line=end_line,
            column=column,
            end_column=end_column,
        ),
    )


def error(
    message: object,
    *,
    title: str | None = None,
    file: Path | str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    column: int | None = None,
    end_column: int | None = None,
) -> None:
    issue_command(
        GitHubAnnotationLevel.ERROR.value,
        message,
        properties=_annotation_properties(
            title=title,
            file=file,
            line=line,
            end_line=end_line,
            column=column,
            end_column=end_column,
        ),
    )


def start_group(title: object) -> None:
    issue_command("group", title)


def end_group() -> None:
    issue_command("endgroup")


@contextmanager
def group(title: object) -> Iterator[None]:
    start_group(title)
    try:
        yield
    finally:
        end_group()


def _append_file_text(path: Path | None, content: str) -> bool:
    if path is None:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline=_NEWLINE) as handle:
        handle.write(content)
        if not content.endswith(_NEWLINE):
            handle.write(_NEWLINE)
    return True


def _append_named_value(path: Path | None, name: str, value: object) -> bool:
    normalized_name = name.strip()
    if not normalized_name:
        msg = "GitHub Actions file-command names must not be empty."
        raise ValueError(msg)

    rendered_value = to_command_value(value)
    delimiter = f"SQUID4WIN_{uuid4().hex}"
    content = (
        f"{normalized_name}<<{delimiter}{_NEWLINE}"
        f"{rendered_value}{_NEWLINE}"
        f"{delimiter}{_NEWLINE}"
    )
    return _append_file_text(path, content)


def set_output(name: str, value: object) -> bool:
    return _append_named_value(context().output_path, name, value)


def set_outputs(values: Mapping[str, object]) -> bool:
    output_path = context().output_path
    wrote_output = False
    for name, value in values.items():
        wrote_output = _append_named_value(output_path, name, value) or wrote_output
    return wrote_output


def export_variable(name: str, value: object) -> bool:
    rendered = to_command_value(value)
    os.environ[name] = rendered
    return _append_named_value(context().env_path, name, rendered)


def add_path(path: Path | str) -> bool:
    rendered = to_command_value(path)
    if not rendered:
        return False

    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = rendered if not current_path else f"{rendered}{os.pathsep}{current_path}"
    return _append_file_text(context().path_file, rendered)


def append_path(path: Path | str) -> bool:
    return add_path(path)


def save_state(name: str, value: object) -> bool:
    return _append_named_value(context().state_path, name, value)


def set_secret(secret: str) -> bool:
    if not secret:
        return False

    if is_enabled():
        issue_command("add-mask", secret)
        return True

    return False


def append_step_summary(content: object) -> bool:
    return _append_file_text(context().step_summary_path, to_command_value(content))


class GitHubStepSummary:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def add_raw(self, text: object, *, add_eol: bool = False) -> Self:
        self._parts.append(to_command_value(text))
        if add_eol:
            self._parts.append(_NEWLINE)
        return self

    def add_text(self, text: object, *, add_eol: bool = False) -> Self:
        return self.add_raw(html.escape(to_command_value(text)), add_eol=add_eol)

    def add_heading(self, text: object, *, level: int = 1) -> Self:
        if level < 1 or level > 6:
            msg = "GitHub step summary headings must use a level between 1 and 6."
            raise ValueError(msg)

        self._parts.append(f"{'#' * level} {html.escape(to_command_value(text))}{_NEWLINE}")
        return self

    def add_code_block(self, text: object, *, language: str | None = None) -> Self:
        language_label = "" if language is None else language.strip()
        self._parts.append(f"```{language_label}{_NEWLINE}")
        self._parts.append(to_command_value(text))
        self._parts.append(f"{_NEWLINE}```{_NEWLINE}")
        return self

    def add_list(self, items: Sequence[object], *, ordered: bool = False) -> Self:
        for index, item in enumerate(items, start=1):
            prefix = f"{index}." if ordered else "-"
            self._parts.append(f"{prefix} {html.escape(to_command_value(item))}{_NEWLINE}")
        return self

    def add_separator(self) -> Self:
        self._parts.append(f"---{_NEWLINE}")
        return self

    def add_break(self) -> Self:
        self._parts.append(f"<br>{_NEWLINE}")
        return self

    def stringify(self) -> str:
        return "".join(self._parts)

    def clear(self) -> Self:
        self._parts.clear()
        return self

    def write(self, *, overwrite: bool = False) -> bool:
        summary_path = context().step_summary_path
        if summary_path is None:
            return False

        rendered = self.stringify()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if overwrite else "a"
        with summary_path.open(mode, encoding="utf-8", newline=_NEWLINE) as handle:
            handle.write(rendered)

        self.clear()
        return True


summary = GitHubStepSummary()
