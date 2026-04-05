from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from squid4win.paths import discover_repository_root

_SKILL_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_SKILL_NAME_LENGTH = 64
_MAX_DESCRIPTION_LENGTH = 1024
_MAX_COMPATIBILITY_LENGTH = 500
_SUPPORTED_FRONTMATTER_FIELDS = (
    "name",
    "description",
    "skill_api_version",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "argument-hint",
    "disable-model-invocation",
    "user-invocable",
    "model",
    "effort",
    "context",
    "agent",
    "hooks",
    "paths",
    "shell",
)


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    name: str
    description: str
    skill_api_version: int
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] | None = None
    allowed_tools: str | list[str] | None = Field(default=None, alias="allowed-tools")
    argument_hint: str | None = Field(default=None, alias="argument-hint")
    disable_model_invocation: bool | None = Field(default=None, alias="disable-model-invocation")
    user_invocable: bool | None = Field(default=None, alias="user-invocable")
    model: str | None = None
    effort: Literal["low", "medium", "high", "max"] | None = None
    context: Literal["fork"] | None = None
    agent: str | None = None
    hooks: dict[str, Any] | list[Any] | None = None
    paths: str | list[str] | None = None
    shell: Literal["bash", "powershell"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field 'name' must be a non-empty string."
            raise ValueError(msg)
        if len(normalized) > _MAX_SKILL_NAME_LENGTH:
            msg = f"Field 'name' must be at most {_MAX_SKILL_NAME_LENGTH} characters."
            raise ValueError(msg)
        if not _SKILL_NAME_PATTERN.fullmatch(normalized):
            msg = (
                "Field 'name' must use lowercase letters, digits, and single hyphens only, "
                "without leading or trailing hyphens."
            )
            raise ValueError(msg)
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field 'description' must be a non-empty string."
            raise ValueError(msg)
        if len(normalized) > _MAX_DESCRIPTION_LENGTH:
            msg = f"Field 'description' must be at most {_MAX_DESCRIPTION_LENGTH} characters."
            raise ValueError(msg)
        return normalized

    @field_validator("skill_api_version")
    @classmethod
    def validate_skill_api_version(cls, value: int) -> int:
        if value != 1:
            msg = "Field 'skill_api_version' must be 1 for repo-owned Copilot skills."
            raise ValueError(msg)
        return value

    @field_validator("license", "compatibility", "argument_hint", "model", "agent")
    @classmethod
    def validate_optional_strings(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            msg = f"Field '{info.field_name}' must not be empty when provided."
            raise ValueError(msg)

        if info.field_name == "compatibility" and len(normalized) > _MAX_COMPATIBILITY_LENGTH:
            msg = f"Field 'compatibility' must be at most {_MAX_COMPATIBILITY_LENGTH} characters."
            raise ValueError(msg)

        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None

        normalized: dict[str, str] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            item_text = str(item).strip()
            if not key_text:
                msg = "Field 'metadata' must not contain empty keys."
                raise ValueError(msg)
            if not item_text:
                msg = f"Field 'metadata.{key_text}' must not be empty."
                raise ValueError(msg)
            normalized[key_text] = item_text
        return normalized

    @field_validator("allowed_tools", "paths")
    @classmethod
    def validate_string_or_string_list(
        cls,
        value: str | list[str] | None,
        info: Any,
    ) -> str | list[str] | None:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                msg = f"Field '{info.field_name}' must not be empty when provided."
                raise ValueError(msg)
            return normalized

        if not value:
            msg = f"Field '{info.field_name}' must not be an empty list."
            raise ValueError(msg)

        normalized_items = [item.strip() for item in value]
        if any(not item for item in normalized_items):
            msg = f"Field '{info.field_name}' must contain only non-empty strings."
            raise ValueError(msg)
        return normalized_items

    @model_validator(mode="after")
    def validate_context_requirements(self) -> SkillFrontmatter:
        if self.agent is not None and self.context != "fork":
            msg = "Field 'agent' requires 'context: fork'."
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class SkillFrontmatterLintResult:
    skills_root: Path
    validated_skills: tuple[Path, ...]
    issues: tuple[str, ...]


def _split_frontmatter(document: str, *, skill_file: Path) -> tuple[str, str]:
    content = document.removeprefix("\ufeff")
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        msg = f"{skill_file}: SKILL.md must start with YAML frontmatter delimited by '---'."
        raise ValueError(msg)

    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        msg = f"{skill_file}: YAML frontmatter must be closed by a second '---' line."
        raise ValueError(msg)

    frontmatter = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        msg = (
            f"{skill_file}: SKILL.md must include a non-empty Markdown body "
            "after the frontmatter."
        )
        raise ValueError(msg)

    return frontmatter, body


def _parse_frontmatter(skill_file: Path) -> SkillFrontmatter:
    raw_content = skill_file.read_text(encoding="utf-8")
    frontmatter_text, _ = _split_frontmatter(raw_content, skill_file=skill_file)

    parsed = yaml.safe_load(frontmatter_text)
    if parsed is None:
        msg = f"{skill_file}: YAML frontmatter must be a mapping."
        raise ValueError(msg)
    if not isinstance(parsed, dict):
        msg = f"{skill_file}: YAML frontmatter must be a mapping."
        raise ValueError(msg)

    try:
        return SkillFrontmatter.model_validate(parsed)
    except ValidationError as error:
        messages = []
        for issue in error.errors(include_url=False):
            location = ".".join(str(part) for part in issue["loc"])
            if location:
                messages.append(f"{skill_file}: frontmatter field '{location}': {issue['msg']}")
            else:
                messages.append(f"{skill_file}: {issue['msg']}")
        msg = "\n".join(messages)
        raise ValueError(msg) from error


def _skill_directories(skills_root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (path for path in skills_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    )


def lint_repo_owned_skills(
    *,
    repository_root: Path | None = None,
    skills_root: Path | None = None,
) -> SkillFrontmatterLintResult:
    repo_root = discover_repository_root(repository_root)
    resolved_skills_root = skills_root or repo_root / "skills"
    issues: list[str] = []

    if not resolved_skills_root.exists():
        issues.append(f"{resolved_skills_root}: skills root does not exist.")
        return SkillFrontmatterLintResult(
            skills_root=resolved_skills_root,
            validated_skills=(),
            issues=tuple(issues),
        )

    if not resolved_skills_root.is_dir():
        issues.append(f"{resolved_skills_root}: skills root must be a directory.")
        return SkillFrontmatterLintResult(
            skills_root=resolved_skills_root,
            validated_skills=(),
            issues=tuple(issues),
        )

    skill_directories = _skill_directories(resolved_skills_root)
    if not skill_directories:
        issues.append(f"{resolved_skills_root}: no repo-owned skill directories were found.")
        return SkillFrontmatterLintResult(
            skills_root=resolved_skills_root,
            validated_skills=(),
            issues=tuple(issues),
        )

    validated_skills: list[Path] = []
    for skill_dir in skill_directories:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            issues.append(f"{skill_dir}: missing required SKILL.md file.")
            continue

        try:
            frontmatter = _parse_frontmatter(skill_file)
        except ValueError as error:
            issues.extend(str(error).splitlines())
            continue

        if frontmatter.name != skill_dir.name:
            issues.append(
                f"{skill_file}: frontmatter field 'name' must match the parent directory "
                f"('{skill_dir.name}')."
            )
            continue

        validated_skills.append(skill_dir)

    return SkillFrontmatterLintResult(
        skills_root=resolved_skills_root,
        validated_skills=tuple(validated_skills),
        issues=tuple(issues),
    )


def supported_frontmatter_fields() -> tuple[str, ...]:
    return _SUPPORTED_FRONTMATTER_FIELDS
