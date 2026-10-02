# Agent instructions

These instructions apply to the entire repository. Read them before planning or implementing work.

## Design authority

- `design/` is the ultimate source of truth for product requirements, scope, architecture, and intended behavior.
- CHIP, the project creator, controls `design/`. Agents may create, edit, rename, or delete design files when CHIP explicitly requests or authorizes those changes while collaborating with them. Agents must not change `design/` on their own initiative. Keep authorized changes within the scope CHIP requested; ordinary implementation work does not authorize design changes.
- Only a subsequent document in `design/` can supersede a requirement in an existing design document. Apply the newer document to the requirements it changes; retain the remaining requirements from the earlier documents.
- Agent plans, implementation choices, code, and progress notes cannot override design requirements.
- Keep design documents only in `design/`. Do not create or retain duplicate design proposals, drafts, snapshots, or outdated versions in `progress/` or elsewhere in the repository. When CHIP authorizes a design update, edit the designated document directly; use version control for history. If design-edit authorization is missing, discuss the proposal in chat rather than saving a parallel design document.
- Read the relevant design documents before planning each epic or implementing its tasks. If document order or conflicting requirements are ambiguous, ask CHIP rather than inventing precedence.
- If requested work conflicts with the design, identify the conflict and ask CHIP to resolve it through a subsequent design document before implementing the conflicting behavior. Continue independent work that remains consistent with the design.

## Agent planning area

- `progress/` is the agent-maintained area for plans, execution notes, and completion tracking.
- Name epic directories `progress/<design-number>_<part-number>_<descriptive-name>/`. The first number identifies the primary governing design document; the second identifies a stable implementation part within that design. For example, `1_1_mvp_vertical_slice_1` is part 1 of `design/1_mvp.html`, later MVP parts use `1_2_...`, `1_3_...`, and the first ingress part is `3_1_game_info_ingress` under `design/3_game_info_ingress.html`. Start part numbers at 1, reuse existing parts, and do not renumber them when their status changes. Keep the existing `0_init_apps` bootstrap directory as a legacy exception. Plans may reference additional governing design documents.
- Plans and execution notes must reference the governing documents in `design/` rather than copy them. They may record implementation details and validation evidence, but must not serve as alternate product design documents.
- For each epic, maintain both of these plans:
  - `progress/<epic>/backend/plan.md`
  - `progress/<epic>/front_end/plan.md`
- Use the existing `front_end` spelling. Backend and frontend are sibling directories; do not nest one under the other.
- Reuse existing epic directories and plans. Preserve completed work and useful history instead of replacing them on each loop.
- If an epic requires no work in one area, keep its plan and state why that area is not applicable.
- Deliver plans as settled, actionable implementation plans. Resolve scope, behavior, API/data contracts, and implementation choices during planning; do not add tasks such as “finalize contracts,” “consider options,” or “discuss requirements” that defer the planning work to implementation.
- When a decision requires CHIP’s input, initiate that discussion before finishing the plan. Continue independent planning while awaiting the answer, but label affected plans as blocked drafts until the decision is resolved. Do not present unresolved proposals as a final plan or bury the required discussion in a future task.
- Make routine implementation choices within the governing design using agent judgment. Ask CHIP about actual ambiguity, conflicting design requirements, or product decisions that cannot be resolved from existing authority. Record settled decisions in the plans; any required design change still follows the design-authority rules above.

## Planning and execution loop

1. Read the relevant design documents and existing epic plans; inspect the current implementation.
2. Create or update both plans before starting implementation. Reference the design documents that authorize the work.
3. Split the epic into small, independently reviewable tasks with stable IDs, a concrete scope, dependencies where needed, acceptance criteria, and appropriate validation.
4. Work through the tasks in dependency order. Mark the current task as in progress and keep the plans aligned when shared API or data contracts change.
5. Validate each task against its acceptance criteria and the governing design. Record the result and any limitations.
6. Mark a task complete only when its implementation and required validation are complete. Record the affected files and validation evidence so the work is reviewable.
7. At the end of each loop, update task statuses, summarize completed work, and identify the next task or unresolved blockers. An epic is complete only when all applicable tasks in both plans are complete and the epic's acceptance criteria are satisfied.

## Plan format and progress tracking

Each `plan.md` must include:

- Epic objective and references to governing design documents.
- Area status: `not_started`, `in_progress`, `blocked`, `complete`, or `not_applicable`.
- A task checklist using unchecked boxes for unfinished tasks and checked boxes for completed tasks.
- For each task: stable ID (for example, `BE-01` or `FE-01`), status, scope, dependencies, acceptance criteria, validation, and completion notes.
- A loop log recording the date, completed task IDs, validation results, blockers, and next steps.

Example task:

```markdown
- [ ] BE-01 — Add games endpoint
  - Status: not_started
  - Scope: Describe the bounded change and relevant design requirement.
  - Dependencies: None.
  - Acceptance criteria: Describe observable behavior required for completion.
  - Validation: Specify the relevant checks.
  - Completion notes: Record affected files and actual validation results when done.
```

Task statuses are `not_started`, `in_progress`, `blocked`, and `complete`. Set the checkbox to `[x]` only for `complete`. A blocked task must explain the blocker and what is needed to resolve it. Do not mark incomplete or unvalidated work complete merely because a loop has ended.
