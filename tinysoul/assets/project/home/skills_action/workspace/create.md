# Workspace Create

Create a new bounded UTF-8 Workspace text resource. In the action instruction,
state the current goal, useful scope, and a reasonable approximate size when
that helps the outer plan. Pass every existing Workspace source used by the
internal task through exact `reference_links`.

If the requested result exceeds the Workspace limit, choose a natural fragment
or bounded artifact for this action and continue with `workspace.append` or
`workspace.patch` according to the next change. Do not assume that every action
must produce one fixed-size chapter. In user-facing documents, cite stable public URLs,
DOI links, or arXiv links when available; keep `workspace:` links internal.
Return only the complete UTF-8 text artifact.
