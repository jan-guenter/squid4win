from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import DictLoader, Environment, FileSystemLoader, StrictUndefined


def create_template_environment(template_root: Path | None = None) -> Environment:
    search_root = template_root or (Path(__file__).resolve().parent / "templates")
    loader = FileSystemLoader(str(search_root)) if search_root.exists() else DictLoader({})

    return Environment(
        loader=loader,
        autoescape=False,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
    )


def render_template_string(template_text: str, /, **context: Any) -> str:
    return create_template_environment().from_string(template_text).render(**context)
