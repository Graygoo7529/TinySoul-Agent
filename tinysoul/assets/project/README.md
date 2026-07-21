# TinySoul Project

This directory is an editable TinySoul project. Configure at least one provider in `configs/llm.providers.toml`, put its API key in `.env`, and then run:

```powershell
tinysoul start --root . --mode normal
```

All providers are disabled in the generated template. TinySoul reports a configuration error until at least one provider used by the configured task models is enabled.

Persistent Agent Home content is under `home/`. Runtime Session, Workspace, and Home overlay state are created under `runtime/`; daily Session, Workspace, and Trash archives are created under `archive/`; consolidated date memories are written under `memory/`.
