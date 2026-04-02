---
name: gfm
description: Review and improve GitHub Flavored Markdown for repository files, issues, pull requests, discussions, and wikis.
skill_api_version: 1
---

# GitHub Flavored Markdown

Use this skill when you need to review, revise, or author Markdown that will be
rendered on GitHub.

It is optimized for repository files first, then for issues, pull requests,
discussions, and wikis.

## Use this skill for

- improving Markdown structure, navigation, and readability on GitHub
- fixing rendering problems in Markdown files or GitHub-authored content
- choosing between headings, lists, tables, callouts, details blocks, and code
  fences
- reviewing or authoring task lists, footnotes, alerts, math, and references
- authoring or repairing Mermaid diagrams intended for GitHub-hosted rendering

## Do not use this skill to

- perform a whole-repository Markdown audit unless explicitly asked
- give vague, generic advice detached from a concrete file or render surface
- change vendored or generated content unless it is explicitly in scope

## Guardrails

- Start with the requested file or files only.
- If a Markdown change describes project state, contracts, behavior, or support
  guarantees, cross-check the relevant source-of-truth files before editing.
- Preserve existing terminology, tone, and information architecture unless the
  task explicitly asks for a rewrite.
- Prefer editing canonical sources rather than generated copies, projections, or
  symlinked mirrors when that distinction matters.

## Working method

1. Identify the render surface before editing:
   - repository Markdown file
   - issue, pull request, or discussion content
   - wiki page
2. Determine the document's job: tutorial, how-to, reference, explanation,
   checklist, status note, release note, ADR, or comment.
3. Review in this order:
   - structure and navigation
   - GitHub rendering behavior
   - advanced formatting
   - diagrams
4. Make surgical changes and explain each one in terms of:
   - rendering correctness
   - navigation and scannability
   - content truthfulness
5. If Mermaid is involved, validate syntax conservatively for GitHub's hosted
   renderer before introducing newer features.

## GitHub-hosted rendering rules that matter

### Headings and navigation

- Use one clear `#` H1 per standalone file unless the file is intentionally an
  embedded fragment.
- Keep heading levels logical. Avoid skipping levels when a normal nested
  structure will do.
- When a file has two or more headings, GitHub exposes an outline in the file
  header.
- Heading anchors are generated from rendered heading text. If you rename a
  heading or reorder duplicate headings, inbound section links can break or
  renumber.
- Custom anchors with `<a name="..."></a>` work, but they do not appear in the
  file outline.

### Links, anchors, and references

- Use relative links for files and images inside the same repository when the
  content lives in the repository.
- In repository Markdown files and wikis, issue and pull request references such
  as `#123` or `owner/repo#123` do not autolink the same way they do inside
  issues and pull requests. Use explicit URLs when a clickable reference is
  required in a file.
- In issues, pull requests, and discussions, bare URLs, issue references, pull
  request references, and commit SHAs autolink.
- Prefer meaningful link text over filler such as "click here".

### Paragraphs, lists, and task lists

- In `.md` files, a plain newline is not enough for a visible line break. Use a
  blank line for a new paragraph, or use two trailing spaces, a backslash, or
  `<br/>` for an intentional line break.
- Keep list markers consistent within a list.
- Indent nested lists so the nested marker aligns beneath the parent item's
  text.
- Use task lists for real actionable work, not decorative bullets.
- If a task item starts with parentheses, escape the first one:
  `- [ ] \(Optional) Follow up later`.

### Tables

- Insert a blank line before a table or GitHub will not render it as a table.
- Use tables for short structured facts, comparisons, and matrices.
- Prefer lists when the content is long-form prose.
- Escape literal pipes inside cells with `\|`.

### Code fences

- Prefer fenced code blocks over indentation.
- Put a blank line before and after fenced code blocks so the raw Markdown stays
  readable.
- Add a language identifier when highlighting helps: `powershell`, `json`,
  `yaml`, `xml`, `mermaid`, `math`, and so on.
- Prefer lower-case language identifiers for portability.
- If you need to show triple backticks literally, wrap them inside quadruple
  backticks.

### Details blocks and minimal HTML

- Use `<details>` with `<summary>` to collapse secondary material such as logs,
  exhaustive examples, or background rationale.
- Keep `<summary>` text short and informative.
- Use the smallest HTML escape hatch that solves the problem.

### Footnotes, alerts, and math

- Footnotes are good for side references and non-blocking detail, but GitHub
  does not support them in wikis.
- Alerts (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`,
  `> [!CAUTION]`) should be rare, important, and not stacked gratuitously.
- Use math only when notation communicates more clearly than prose.
- For block math, use `$$...$$` or a fenced code block with the `math`
  language identifier.

## Mermaid on GitHub

### GitHub-specific constraints

- GitHub renders Mermaid diagrams in issues, discussions, pull requests, wikis,
  and repository Markdown files.
- Always fence Mermaid diagrams with the `mermaid` language identifier.
- GitHub's Mermaid version can lag behind the latest Mermaid documentation, so
  prefer conservative syntax.
- When you need to confirm the available Mermaid version on GitHub, the
  following can help:

````text
```mermaid
info
```
````

### Authoring rules that avoid broken diagrams

- Start with the diagram type on the first non-config line, such as
  `flowchart LR` or `sequenceDiagram`.
- Prefer one statement per line so diffs are readable and syntax errors are
  easier to isolate.
- Use short stable IDs and separate them from reader-facing labels.
- Quote labels that contain spaces, punctuation, Unicode, or other potentially
  ambiguous characters.
- Keep diagrams focused. Split a large diagram into smaller diagrams instead of
  compressing every branch into one picture.
- Mermaid comments use `%%` and should be on their own line.
- Prefer portable core syntax over newer or host-specific features unless you
  have verified support.

### Flowchart-specific traps

- Lowercase `end` can break a flowchart. Capitalize it or quote it if it must
  appear as text.
- `---o` and `---x` create special edge types. If the next node or label starts
  with `o` or `x`, insert a space or capitalize the text.

### Sequence-diagram-specific traps

- The word `end` can also break sequence diagrams. If it must appear as content,
  wrap it in parentheses, quotes, or brackets.
- Use aliases when participant names need line breaks or friendlier display
  labels.

## Markdown review checklist

Before finishing a Markdown edit, check:

- Does the heading outline match the document's job?
- Do relative links, anchors, and heading references still work after edits?
- Are tables, task lists, alerts, and details blocks helping readers instead of
  hiding the core path?
- Are GitHub-specific behaviors described correctly for the chosen render
  surface?
- If project state is described, does it still match the relevant source of
  truth?
- If Mermaid is used, is the syntax conservative enough for GitHub's hosted
  renderer?

## Response expectations

When using this skill:

- avoid vague "make it clearer" advice
- point to specific sections, constructs, or lines when possible
- explain whether a recommendation is about rendering correctness, information
  architecture, or content truthfulness
- avoid whole-repository audits unless explicitly requested

## Sources

- GitHub Docs:
  - [Basic writing and formatting syntax](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax)
  - [Working with advanced formatting](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting)
  - [Creating and highlighting code blocks](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-and-highlighting-code-blocks)
  - [Organizing information with tables](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/organizing-information-with-tables)
  - [Organizing information with collapsed sections](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/organizing-information-with-collapsed-sections)
  - [Autolinked references and URLs](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/autolinked-references-and-urls)
  - [Creating diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)
- Mermaid Docs:
  - [Introduction](https://mermaid.js.org/intro/)
  - [Syntax](https://mermaid.js.org/intro/syntax-reference.html)
