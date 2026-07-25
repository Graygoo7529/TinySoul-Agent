# Session

Use Session only for completed prior Turns. The fixed `background:session:*` messages normally provide recent asks, answers, and Action outcomes; Session ActionResults enter the current TurnTrace and do not change that Background.

Use `session.history.inspect` to locate a Turn or expand a Summary. Once a `session:turn/...` ref is known, use `session.history.actions` for Action counts, outcomes, failures, and trace indexes; use `session.history.recall` only when exact trace entries are needed.

Follow `next_cursor` continuation objects verbatim. Summary refs belong to inspect; Context trace refs belong to Context actions. Restart active-head inspection without a cursor if Session reports that history changed.
