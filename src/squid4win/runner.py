from __future__ import annotations

import os
import subprocess
from logging import Logger
from pathlib import Path

from squid4win.models import AutomationPlan, ProcessInvocation


class PlanExecutionError(RuntimeError):
    """Raised when a planned command cannot be executed successfully."""


class ProcessRunner:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger

    def describe(self, invocation: ProcessInvocation) -> None:
        if invocation.cwd is not None:
            self._logger.info("  cwd %s", invocation.cwd)

        for name, value in sorted(invocation.environment.items()):
            self._logger.info("  env %s=%s", name, value)

        self._logger.info("  %s", invocation.render())

    def run(
        self,
        invocation: ProcessInvocation,
        *,
        default_cwd: Path | None = None,
    ) -> int:
        environment = os.environ.copy()
        environment.update(invocation.environment)
        completed = subprocess.run(
            list(invocation.command),
            check=False,
            cwd=str(invocation.cwd or default_cwd) if (invocation.cwd or default_cwd) else None,
            env=environment,
        )
        if completed.returncode != 0:
            msg = (
                f"{invocation.description} failed with exit code {completed.returncode}: "
                f"{invocation.render()}"
            )
            raise PlanExecutionError(msg)

        return completed.returncode


class PlanRunner:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger
        self._process_runner = ProcessRunner(logger)

    def describe(self, plan: AutomationPlan) -> None:
        self._logger.info("%s", plan.summary)
        for index, command in enumerate(plan.commands, start=1):
            self._logger.info("Step %d/%d: %s", index, len(plan.commands), command.description)
            self._process_runner.describe(command)

    def run(self, plan: AutomationPlan) -> int:
        self.describe(plan)

        for command in plan.commands:
            self._process_runner.run(command, default_cwd=plan.repository_root)

        return 0
