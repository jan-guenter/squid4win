from __future__ import annotations

import logging
import sys
from typing import Final

from squid4win.utils.actions import annotation_level_from_logging, format_annotation, is_enabled

_DEFAULT_FORMAT: Final[str] = "%(levelname)s %(name)s: %(message)s"
_LEVEL_NAMES: Final[tuple[str, ...]] = ("NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_DEFAULT_LEVEL_INDEX: Final[int] = 2
_MINIMUM_VERBOSITY_INDEX: Final[int] = 1


def is_github_actions() -> bool:
    return is_enabled()


class GitHubActionsFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(_DEFAULT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        annotation_level = annotation_level_from_logging(record.levelno)
        if annotation_level is None:
            return rendered

        return format_annotation(
            annotation_level,
            rendered,
            title=getattr(record, "gh_title", None),
            file=getattr(record, "gh_file", None),
            line=getattr(record, "gh_line", None),
            end_line=getattr(record, "gh_end_line", None),
            column=getattr(record, "gh_column", None),
            end_column=getattr(record, "gh_end_column", None),
            enabled=is_enabled(),
        )


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


def level_name_from_verbosity(*, verbose: int = 0, quiet: int = 0) -> str:
    normalized_verbose = max(verbose, 0)
    normalized_quiet = max(quiet, 0)
    index = min(
        max(
            _DEFAULT_LEVEL_INDEX + normalized_quiet - normalized_verbose,
            _MINIMUM_VERBOSITY_INDEX,
        ),
        len(_LEVEL_NAMES) - 1,
    )
    return _LEVEL_NAMES[index]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
