# Compose a Workspace artifact

Provide target_ref, an instruction, optional references and an explicit overwrite choice. An existing target is read completely within the artifact budget before generation; a truncated target cannot be replaced from its prefix. Use read followed by exact edit/append when the target exceeds this budget.

The action returns committed metadata, while generated text stays in the file. If generation is incomplete or too large, reduce the requested artifact or split the work. References are bounded inputs; inspect truncation and choose evidence accordingly. Workspace does not revalidate versions after generation, so shared writers may overwrite each other's changes.

**Use when**: Generating a complete new file, or regenerating an existing small file under the artifact budget. The instruction clearly defines the desired output, and references provide all necessary context.

**Avoid when**: The target file exceeds the artifact budget (typically too large to read entirely); use workspace.read to obtain specific sections, then apply targeted workspace.edit or workspace.append. Do not use compose for incremental changes to known locations; prefer exact edit/append for precision and efficiency.
