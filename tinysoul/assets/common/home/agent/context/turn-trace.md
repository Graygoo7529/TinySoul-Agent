# Turn Trace Context

TurnTrace tells the current Turn in observation order: initial input, appended instructions, decisions, actions and their results, questions, and replies. Inputs also retain the accepted user text. A question result includes its complete options and explanation; a reply names the chosen option and the user's comment.

Recent entries are directly readable. Older groups carry an explanation and a reference such as `turn:trace/2026-10-06/42#node/3`. Use `core.context.inspect` to recall the group, then follow the references it returns. The same root supports `#entry/7`, `#input/0`, and `#action/0`. Copy the actual reference; these examples are not available targets.

An Inspect result is one bounded read. A continuation continues that read; it is unrelated to a model call. Folded reading results recall the target and coverage, not a saved version of the resource body. Working describes the latest state when an earlier Trace fact is stale.
