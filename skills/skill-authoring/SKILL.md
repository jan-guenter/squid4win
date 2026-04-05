---
name: skill-authoring
description: Create and improve repo-owned Copilot skills with lean instructions, realistic evals, evidence-based grading, and repo-safe layout practices.
skill_api_version: 1
---

# Skill authoring

Use this skill when you need to create, review, or iteratively improve a
repo-owned Copilot skill.

## Use this skill for

- deciding whether a task deserves a dedicated skill
- shaping `SKILL.md` around concrete activation conditions and outcomes
- keeping instructions lean, purposeful, and generalizable
- adding supporting references or scripts only when they remove repeated work
- designing `evals/evals.json` cases and with/without-skill comparisons
- reviewing an existing skill for clarity, gaps, and over-constraint

## Do not use this skill for

- vendoring or editing externally synced skills under `.agents\skills\`
- writing a skill before you understand the recurring task it is meant to solve
- stuffing every edge case into one oversized instruction file

## Repo guardrails

- Keep repo-owned skills canonical under `skills\<skill-name>\`.
- Mirror them into `.agents\skills\<skill-name>\` with **file-level symlinks**.
- Keep `.agents\skills\<skill-name>\` itself as a real directory, not a
  symlink.
- Prefer repo-relative symlink targets such as
  `../../../skills/<skill-name>/SKILL.md`.
- Update `skills\README.md` whenever a repo-owned skill is added, renamed,
  removed, or materially re-described.

## Working method

1. Clarify the recurring task before writing anything.
   - What user prompt should activate the skill?
   - What mistakes happen today without the skill?
   - What outputs should become more reliable with the skill?
2. Keep the instruction set lean.
   - Prefer a small number of strong instructions over exhaustive checklists.
   - Explain **why** a behavior matters when that helps the model generalize.
   - Avoid brittle wording that only fits one prompt shape.
3. Separate durable guidance from examples.
   - Put evergreen rules in `SKILL.md`.
   - Add examples only when they clarify a pattern the model might otherwise
     miss.
   - Add `references\*.md` only when you have stable supporting material worth
     reusing across tasks.
4. Add scripts only when repeated work is mechanical.
   - If every successful run writes the same helper script, bundle it into the
     skill's `scripts\` directory.
   - Do not add scripts for one-off convenience or work the model can do more
     directly.
5. Design evals early, but start small.
   - Create `evals/evals.json` with **2-3 realistic prompts** first.
   - Include different phrasings and at least one edge case or boundary case.
   - Prefer prompts that resemble actual user language, file paths, and context.
6. Run each eval against a baseline.
   - Execute every case once with the skill and once without the skill, or
     against a snapshot of the previous skill version.
   - Keep the runs isolated so only the skill changes the outcome.
   - Capture outputs, timing, and token usage if available.
7. Add assertions after you inspect first-run outputs.
   - Use objective checks when possible: files exist, sections appear, counts
     are correct, output is valid JSON, and so on.
   - Avoid vague assertions like "looks good".
   - Require concrete evidence for a `PASS`.
8. Grade with evidence.
   - Record `PASS` or `FAIL` per assertion.
   - Quote the output or file that proves the result.
   - Prefer verification scripts for mechanical checks.
9. Add human review and pattern analysis.
   - Review the actual outputs, not just the grades.
   - Remove assertions that always pass or always fail in both variants.
   - Pay attention to pass-rate, timing, and token trade-offs before adding more
     rules.
10. Iterate leanly.
    - Tighten instructions when results are inconsistent or overly verbose.
    - Generalize from the failures instead of patching one prompt at a time.
    - Stop when improvements flatten and human feedback is consistently empty.

## Minimal eval template

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "Use the skill on a realistic task prompt here.",
      "expected_output": "Describe what success looks like in human terms.",
      "files": [],
      "assertions": [
        "The output includes the required artifact",
        "The explanation is specific and actionable"
      ]
    }
  ]
}
```

## Eval workspace pattern

```text
example-skill/
├── SKILL.md
└── evals/
    └── evals.json
example-skill-workspace/
└── iteration-1/
    ├── eval-1/
    │   ├── with_skill/
    │   │   ├── outputs/
    │   │   ├── timing.json
    │   │   └── grading.json
    │   └── without_skill/
    │       ├── outputs/
    │       ├── timing.json
    │       └── grading.json
    └── benchmark.json
```

## Grading and human review

- Store pass/fail results with specific evidence, not just summary labels.
- Use human review notes for qualities that assertions miss: usefulness,
  structure, tone, visual clarity, and whether the result actually solves the
  user's problem.
- Keep reviewer feedback short and actionable so it can guide the next
  iteration.

## Review checklist

Before finishing a skill change, check:

- Is the activation scope obvious from the first screenful of the skill?
- Are the instructions about **how** to think and act, not just what to copy?
- Can the skill handle more than one prompt phrasing?
- Are examples and references earning their weight?
- Does the skill have at least a seed eval plan, even if the eval files are not
  added yet?
- Is there a credible with/without-skill comparison plan?
- If this is a repo-owned skill, are the mirror directory and symlinks laid out
  correctly?

## Evaluation seeds

- "Create a new repo-owned skill for a narrow recurring task and propose a first
  `evals/evals.json` with two prompts and one edge case."
- "Review an existing skill that has become too long and suggest how to trim it
  without losing the important guardrails."
- "Compare the current skill against a no-skill baseline and explain whether the
  extra tokens and time are buying better results."

## Sources

- Agent Skills:
  - [Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills)
