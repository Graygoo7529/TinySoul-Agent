# TinySoul Project

This directory is an editable TinySoul project created from one packaged config profile. The profile only selected the initial files; this project now owns and may edit its `configs/` and `home/` independently.

The default `standard` profile keeps every LLM provider disabled and leaves host-sensitive optional capabilities disabled. The `development` profile carries the repository maintainer's enabled provider and capability configuration; it still contains no credentials and does not install optional distributions or host executables.

Review `configs/llm.providers.toml`, copy the required names from `.env.example` into a local `.env`, and ensure every enabled capability dependency is installed. Then run:

```powershell
tinysoul start --root . --mode normal
```

Projects created with the standard profile report a configuration error until at least one provider used by the configured task models is enabled. Development-profile projects fail at the owning module boundary when an enabled provider credential, optional distribution, or host executable is unavailable.

Persistent Agent Home content is under `home/`. Runtime Session, Workspace, and Home overlay state are created under `runtime/`; daily Session, Workspace, and Trash archives are created under `archive/`; consolidated date memories are written under `memory/`.
