---
name: gfm
description: Review and improve GitHub Flavored Markdown for squid4win with GitHub-hosted rendering, advanced formatting, and Mermaid guidance.
skill_api_version: 1
---

# GitHub Flavored Markdown for squid4win

Use this skill when you need to review, revise, or author Markdown that will be
read on GitHub. It is optimized for repository Markdown files first, then for
issues, pull requests, discussions, and wikis.

This is not a license to audit the whole repository. Stay within the requested
scope unless the user explicitly asks for a broader Markdown review.

## Use this skill for

- improving Markdown structure, navigation, and readability on GitHub
- fixing rendering problems in repository `.md` files
- choosing between headings, lists, tables, callouts, details blocks, and code
  fences
- reviewing or authoring task lists, footnotes, alerts, math, and references
- authoring or repairing Mermaid diagrams intended for GitHub-hosted rendering

## Do not use this skill to

- perform a whole-repository Markdown audit unless asked
- give vague, generic writing advice disconnected from a concrete file or
  render surface
- change vendored third-party skills unless they are explicitly in scope

## squid4win guardrails

- Start with the requested file or files only.
- If a Markdown change affects repository state claims, cross-check
  `README.md`, `AGENTS.md`, and the relevant ADRs under `.agents\design\`.
- Keep docs truthful about committed automation, local validation, and
  not-yet-proven behavior.
- Preserve Windows-style paths when showing commands or repository paths.
- Preserve current artifact names such as `squid4win.msi` and
  `squid4win-portable.zip` unless the task explicitly changes that contract.
- Treat `.agents\skills\` as externally synced skill content plus symlinks for
  repo-owned skills; edit repo-owned skills via their canonical `skills\...`
  paths unless the symlink behavior itself is in scope.

## Working method

1. Identify the render surface before editing:
   - repository Markdown file
   - issue, pull request, or discussion comment/body
   - wiki page
2. Determine the document's job: tutorial, how-to, reference, explanation,
   status note, checklist, release note, ADR, or comment.
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
- When a file has two or more headings, GitHub exposes a file outline/table of
  contents in the file header.
- Heading anchors are generated from rendered heading text. If you rename a
  heading or reorder duplicate headings, inbound section links can break or
  renumber.
- Custom anchors with `<a name="..."></a>` work, but they do not appear in the
  file Outline/TOC.

### Links, anchors, and references

- Use relative links for other files and images inside the repository.
- In repository Markdown files and wikis, issue and pull request references such
  as `#123`, `GH-123`, or `owner/repo#123` do **not** autolink. If a repo file
  needs a clickable issue or PR reference, use an explicit URL.
- In issues, pull requests, and discussions, bare URLs, issue/PR references,
  and commit SHAs autolink.
- If you need to avoid a backlink from one GitHub conversation item to another,
  GitHub documents using `redirect.github.com` instead of `github.com`.
- Keep link text on one line.
- Prefer meaningful link text over vague filler like "click here."

### Paragraphs, lists, and task lists

- In `.md` files, a plain newline is not enough for a visible line break. Use a
  blank line for a new paragraph, or use two trailing spaces, a backslash, or
  `<br/>` for an intentional line break.
- Keep list markers consistent within a list.
- Nested lists should be indented so the nested marker sits under the parent
  item's text, not at a random column.
- Use task lists for real actionable work, not decorative bullets.
- If a task item starts with parentheses, escape the first one:
  `- [ ] \(Optional) Follow up later`.
- GitHub retired tasklist blocks. When issue hierarchy matters, prefer
  sub-issues instead of relying on Markdown structure alone.
- Issue bodies gain extra task-list tracking behavior. Do not assume repository
  files have the same workflow semantics.

### Tables

- Insert a blank line before a table or GitHub will not render it as a table.
- Use tables for matrix data, comparisons, compatibility grids, and other short
  structured facts.
- Prefer lists when content is long-form prose or multi-paragraph explanation.
- Escape literal pipes inside cells with `\|`.
- Use alignment markers only when they help readers scan values such as status,
  numbers, or yes/no columns.

### Code fences

- Prefer fenced code blocks over indentation.
- Put a blank line before and after fenced code blocks so the raw Markdown stays
  readable.
- Add a language identifier when highlighting helps: `powershell`, `json`,
  `yaml`, `xml`, `mermaid`, `math`, and so on.
- Prefer lower-case language identifiers. GitHub documents this as the safe
  choice when the content may also appear on GitHub Pages.
- If you need to show triple backticks literally, wrap them inside quadruple
  backticks.

### Details blocks and minimal HTML

- Use `<details>` with `<summary>` to collapse secondary detail such as logs,
  exhaustive examples, reference output, or rationale that would otherwise bury
  the main path.
- Keep `<summary>` text short and informative.
- Use `<details open>` only when the default expanded state is intentionally
  important.
- Supported HTML helpers shown in GitHub Docs include `<sub>`, `<sup>`,
  `<ins>`, `<a name>`, `<br/>`, `<picture>`, and `<span>` for certain math
  dollar-sign cases. Prefer the smallest HTML escape hatch that solves the
  problem.

### Footnotes, alerts, and math

- Footnotes are good for side references and non-blocking detail, but GitHub
  does not support footnotes in wikis.
- Alerts (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`,
  `> [!CAUTION]`) should be rare, important, and never consecutive or nested in
  other elements.
- Use math only when notation communicates more clearly than prose.
- GitHub supports inline math with standard dollar delimiters, plus the
  alternate inline form documented by GitHub when normal Markdown punctuation
  would conflict with the expression.
- For block math, use `$$...$$` or a fenced code block with the `math`
  language identifier.
- If a literal dollar sign shares a line with math, escape the in-math dollar
  sign as `\$` or wrap the non-math dollar sign in `<span>$</span>` as GitHub
  documents.

## Mermaid on GitHub

### GitHub-specific constraints

- GitHub renders Mermaid diagrams in issues, discussions, pull requests, wikis,
  and repository Markdown files.
- Always fence Mermaid diagrams with the `mermaid` language identifier.
- GitHub also supports `geojson`, `topojson`, and `stl` fenced blocks. Use
  those only when the content is actually map or 3D-model data; for normal
  documentation diagrams, Mermaid is usually the right fit.
- GitHub's Mermaid version can lag behind the latest Mermaid documentation. When
  you want to use newer syntax, check the version GitHub currently exposes with:

````text
```mermaid
info
```
````

- GitHub warns that third-party Mermaid plugins can cause errors when Mermaid
  syntax is used on GitHub.

### Authoring rules that avoid broken diagrams

- Start with the diagram type on the first non-config line, such as
  `flowchart LR` or `sequenceDiagram`.
- Prefer one statement per line so diffs are readable and syntax errors are
  easier to isolate.
- Use short, stable IDs and separate them from reader-facing labels.
- Quote labels that contain spaces, punctuation, Unicode, or words that may be
  parsed specially.
- Keep diagrams focused. Split a large diagram into multiple smaller diagrams
  instead of compressing every branch into one picture.
- Mermaid comments use `%%` and should be on their own line.
- Mermaid's syntax reference documents that `%%{` and `}%%` can confuse the
  renderer. Avoid `{}` inside Mermaid comments.
- Prefer portable core syntax over site-specific configuration. Use frontmatter,
  directives, new shapes, or advanced layout/look features only after
  confirming that GitHub's Mermaid version supports them.

### Flowchart-specific traps

- Lowercase `end` can break a flowchart. Capitalize it or wrap it in quotes if
  it must appear as text.
- `---o` and `---x` create special edge types. If the next node or label starts
  with `o` or `x`, insert a space or capitalize the text to avoid accidental
  circle or cross edges.
- Mermaid documents quoted labels for Unicode text and Markdown-formatted text;
  use them when a plain token would be ambiguous.

### Sequence-diagram-specific traps

- The word `end` can also break sequence diagrams. If it must appear as content,
  wrap it in parentheses, quotes, or brackets.
- Use aliases when participant names need line breaks or more readable display
  labels.

### When a diagram should become prose instead

- If the content mostly lists facts with no meaningful relationships, use bullets
  or a table instead.
- If the diagram needs a long legend to be understood, simplify or split it.
- If readers mainly need step-by-step instructions, keep the main path in prose
  and use a diagram only as reinforcement.

## Repo-oriented Markdown review checklist

Before finishing a Markdown review or edit, check:

- Does the heading outline match the document's job?
- Do relative links, anchors, and heading references still work after edits?
- Are tables, task lists, alerts, and details blocks helping readers instead of
  hiding core content?
- Are GitHub-only behaviors described correctly for the chosen render surface?
- If repository state is described, does it still match `README.md`, `AGENTS.md`,
  and the relevant ADRs?
- If Mermaid is used, is the syntax conservative enough for GitHub's hosted
  renderer?

## Response expectations

When using this skill:

- do not give vague "make it clearer" advice
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
  - [Writing mathematical expressions](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions)
  - [About tasklists](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/about-tasklists)
  - [Creating diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)
- Mermaid Docs:
  - [Intro](https://mermaid.js.org/intro/)
  - [Syntax reference](https://mermaid.js.org/intro/syntax-reference.html)
  - [Flowcharts](https://mermaid.js.org/syntax/flowchart.html)
  - [Sequence diagrams](https://mermaid.js.org/syntax/sequenceDiagram.html)
