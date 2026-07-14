# TinySoul Daily Lifecycle

TinySoul separates deterministic daily rollover from review-driven Home and Memory maintenance so operational archives never depend on an LLM decision.

Session, Workspace, and active Trash roll over at the Business Day boundary. The active Home overlay remains effective until Home Maintenance reviews it, while Memory Maintenance derives one date-scoped MEMORY from the archived Session facts.

Related guidance: <home:why@separate-rollover-maintenance> and <home:how@daily-home-review>.
