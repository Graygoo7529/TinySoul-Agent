# Workspace

Workspace files are the daily resource facts. Use workspace.list to discover directories and metadata, workspace.search for literal/regex discovery, real backlinks, or directory/refs combined with filter/select/rerank, and workspace.inspect for current text, selected line/heading ranges, directories, and continuation pages. Images and documents require their corresponding resource or analysis capability; do not assume every reference is text.

Use workspace.write for exact content, workspace.edit for ordered unambiguous replacements, and workspace.append for exact additions. Edits are validated together before one file replacement. Use workspace.compose when a model must generate a complete bounded artifact, and workspace.analyze for a grounded answer from explicitly selected complete text references. Pass only workspace: references as references. Inspect bodies enter the Action result; generation inputs stay local to their actions. File bodies do not become Working state.

Use move/mkdir to organize resources, delete/restore/trash_list for recoverable deletion, and tag for pinned/tmp/library annotations. Tags do not change the daily lifecycle. A library tag does not move the file into a separate knowledge library.

Writes create by default; overwrite must be explicit. Workspace does not use content-version guards. Concurrent scripts or users can modify files, so inspect current contents before making decisions. File effects remain after cancellation. Context pressure does not delete files.
