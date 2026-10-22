# Inspect a Workspace resource

Pass the exact reference returned by Search or another action. A text reference may select a line range or Markdown heading. The selection chooses what to read; max_chars limits the body returned on this page. Read the returned coverage before concluding that the entire selection was examined.

If more content is needed, call workspace.inspect again with the same ref and its returned continuation. A continuation belongs to this reading operation and current resource content. If it is unavailable or rejected after an edit, inspect the resource again to read its current state.

Directories disclose their direct children with descriptions and references. Non-text resources disclose metadata; use an available resource reading or conversion capability to obtain their content.

The returned page enters the current Turn as an action result. Later compression and Session history retain what was inspected and its coverage, not a saved copy of the old body. To obtain content again, inspect the current resource.

**Use when**: Obtaining structured metadata and bounded content from a Workspace reference, especially when the exact extent is unknown or when inspecting directories. Inspect supports continuation for large text and provides coverage information.

**Avoid when**: You need simple line-range text reading without metadata; use workspace.read directly. For semantic search across multiple files, use workspace.search. Inspect is not a substitute for targeted read or search operations.
