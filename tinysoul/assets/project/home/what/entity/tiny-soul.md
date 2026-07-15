# TinySoul

TinySoul is the agent represented by this project. It coordinates provider-neutral model tasks, constructed Context, explicit Actions, daily Workspace and Session state, persistent Agent Home knowledge, and independent date Memory.

TinySoul keeps ownership boundaries explicit: Context owns the model-facing projection, domain modules own their persistent facts, Loop owns execution order, and App owns process assembly and external input.

Related concepts: <home:what@concept/context-and-links> and <home:what@concept/daily-lifecycle>. Related guidance: <home:how@tinysoul-docs>.
