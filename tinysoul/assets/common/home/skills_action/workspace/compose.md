# Compose a Workspace artifact

Provide target_link, an instruction, optional reference_links and an explicit overwrite choice. An existing target is read completely within the artifact budget before generation; a truncated target cannot be replaced from its prefix. Use read followed by exact edit/append when the target exceeds this budget.

The action returns committed metadata, while generated text stays in the file. If generation is incomplete or too large, reduce the requested artifact or split the work. References are bounded inputs; inspect truncation and choose evidence accordingly. Workspace does not revalidate versions after generation, so shared writers may overwrite each other's changes.
