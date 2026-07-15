# Why Rollover and Maintenance Are Separate

Daily rollover must remain deterministic because a new Business Day cannot depend on model availability, review decisions, or terminal interaction.

Home Maintenance and Memory Maintenance are independent Program work. They may run later, fail independently, and leave their durable inputs available for a future retry.

Related concept: <home:what@concept/daily-lifecycle.md>.
