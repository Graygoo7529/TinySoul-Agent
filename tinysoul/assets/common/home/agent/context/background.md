# Background Context

Background is the surrounding context of the current Turn: identity, prior-Turn Session history, accepted current inputs, and loaded Home or Memory knowledge. It is available to each task, but can be loaded or refined during the Turn. Phase1 may load relevant Home Top references, and accepted Session actions may revise the semantic map.

A Top reference identifies content that can be loaded, not the content body. Automatically loaded entries are already usable; load another exposed Top reference only when its body is needed. Catalog metadata is an index, not loaded knowledge.

Session presents a semantic map followed by chronological interaction text from completed Turns. The map connects topics, interpretations and shared history references; the text preserves original inputs, appended constraints, questions, ordered options, replies and confirmed answers once per Turn. Unclassified Turns remain available. Interpretations are source-backed judgments, not changes to recorded facts.

Use `core.context.inspect` with `session:map` or an exposed reference to navigate topics, history and precise evidence. A folded or excerpted Turn retains its reference for complete paginated reading. When new evidence changes your understanding, `core.session.organize` can revise topics and relations in a User Turn. Current accepted inputs and settled actions may support a revision, but the active Turn is not completed history.

Use TurnTrace for current-Turn interaction and environment observations. Use Working for the latest plan and resource or Job projections.
