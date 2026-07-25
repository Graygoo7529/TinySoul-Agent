# Session

Use Session only for completed prior Turns. Fixed `background:session:*` messages normally provide recent asks, answers, Action outcomes, and one Action collection ref per Turn. Session ActionResults enter the current TurnTrace and do not change that Background.

Use `session.history.inspect` to expand refs from the active head through Summary, Turn, and Action collection nodes. An Action collection may be filtered by an Action name already visible in Background. Use `session.history.recall` only with a concrete `session:turn/...#action/...` ref returned by inspect.

Copy refs and `next_cursor` objects verbatim. Do not construct or interpret Action suffixes. Current-Turn trace refs belong to Context actions; restart active-head inspection without a cursor if Session reports that history changed.
