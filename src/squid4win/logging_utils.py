from __future__ import annotations

import logging
import os
import sys
from typing import Final

_DEFAULT_FORMAT: Final[str] = "%(levelname)s %(name)s: %(message)s"


def is_github_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"


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


class GitHubActionsFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(_DEFAULT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        command = self._annotation_command(record.levelno)
        if command is None or not is_github_actions():
            return rendered

        properties: list[str] = []
        for attribute_name, property_name in (
            ("gh_title", "title"),
            ("gh_file", "file"),
            ("gh_line", "line"),
            ("gh_end_line", "endLine"),
            ("gh_column", "col"),
            ("gh_end_column", "endColumn"),
        ):
            value = getattr(record, attribute_name, None)
            if value is not None:
                properties.append(f"{property_name}={_escape_command_property(str(value))}")

        prefix = f"::{command}"
        if properties:
            prefix = f"{prefix} {','.join(properties)}"

        return f"{prefix}::{_escape_command_message(rendered)}"

    @staticmethod
    def _annotation_command(level: int) -> str | None:
        if level >= logging.ERROR:
            return "error"
        if level >= logging.WARNING:
            return "warning"
        return None


def configure_logging(level: str = "INFO", *, force: bool = False) -> logging.Logger:
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    if root_logger.handlers and not force:
        root_logger.setLevel(numeric_level)
        return root_logger

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(GitHubActionsFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)
    logging.captureWarnings(True)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
