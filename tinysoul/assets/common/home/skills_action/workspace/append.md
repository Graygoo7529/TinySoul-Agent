# Append exact text

Provide target_ref and the exact text fragment. No separator or newline is inserted automatically. Use workspace.edit for replacing an existing span or workspace.compose for model-generated complete content. Changes apply directly to current files and remain after cancellation.

**Use when**: Adding known literal text to the end of an existing file, such as appending log entries, additional test cases, or imports. The text to append is already determined and does not require model generation.

**Avoid when**: The new content requires model generation or synthesis from instructions; use workspace.compose instead. For replacing or modifying existing content, use workspace.edit. Append is not suitable for inserting text at arbitrary positions within a file.
