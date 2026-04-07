# Disney Pins

A repo for managing a Disney pin selling business.

## Planning workflow

When the user asks to plan, design, or build something new:

1. **Brainstorm first** — Use the `superpowers:brainstorming` skill to explore the idea, ask clarifying questions, propose approaches, and produce a design spec. Do not skip this even if the user says "create a festival" or "plan this."
2. **Write the plan** — After the spec is approved, use the `superpowers:writing-plans` skill to create the implementation plan. This is where Festival structure gets created.
3. **Execute via Festival** — Once the plan exists, use Festival to execute scoped tasks.

The sequence is always: **brainstorm → spec → plan → Festival execution**. Do not jump directly to Festival creation without a spec.

## Festival workflow

When working on scoped implementation tasks in this repository:

1. Run `fest intro` at the start of a new Festival session if needed.
2. Use `fest next` to get the next assigned task.
3. Execute only the scoped task unless the task says otherwise.
4. When finished, follow the task completion steps, including `fest task completed`.
5. Prefer `fest commit -m "..."` over raw git commit when working inside a Festival workflow.

Do not use Festival for exploratory design unless explicitly asked.
Use normal prompting for discovery, architecture discussion, and ambiguous work.
