# Read Workspace text

Provide an exact Workspace text reference. Small text may be read directly; use inclusive start_line/end_line and the returned cursor to page larger ranges. Cursors refer to current contents, so restart the range after an external edit. Use search or list to locate resources first. This action does not interpret binary documents or images.

**Use when**: Reading known text files by exact reference, especially when targeting specific line ranges. This is the primary action for obtaining file content to feed into compose, edit, analyze, or manual reasoning.

**Avoid when**: You need structured metadata or directory listings; use workspace.inspect instead. For locating files semantically or by pattern, use workspace.search first.
