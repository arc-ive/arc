"""Agent evaluation — DEFERRED (Issue #139, V2-ADR-023).

The following ADR-023 Agent criteria require the Agent execution loop,
which is not currently implemented:

1. Step bounds — Agent must enforce maximum iterations per run
2. Correct skill selection — Agent must select appropriate skill from catalog
3. Authorization preservation — Agent must carry authorization through execution
4. Approval behavior — Agent must enforce REQUIRE_HUMAN_APPROVAL on high-risk skills
5. Termination — Agent must terminate on completion, error, or step bound

These cannot be evaluated until the Agent feature is implemented.
This file exists as a tracking placeholder per Issue #139.
"""
