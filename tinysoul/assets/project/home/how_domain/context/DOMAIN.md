# Context

Use Context only for compressed interaction history from the current Turn. Continue directly when the needed decision or result is still visible.

Use `context.trace.inspect` to navigate a heap head or branch, then `context.trace.recall` for a leaf's exact entries. Use `context.trace.fold` when expanded foldable results are no longer needed.

Use Session for completed prior Turns.
