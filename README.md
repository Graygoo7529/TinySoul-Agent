# TinySoul

TinySoul is a local, provider-neutral LLM agent runtime built around explicit Context, Action, Session, Workspace, Agent Home, Memory, and daily lifecycle boundaries.

## Install And Initialize

TinySoul requires Python 3.13 or newer.

```powershell
python -m pip install .
tinysoul init my-agent
cd my-agent
```

`tinysoul init` copies editable configuration and Home templates into a new or empty directory. It does not select a provider and never overwrites a non-empty directory. Enable at least one provider in `configs/llm.providers.toml`, put its key in `.env`, and run:

```powershell
tinysoul start --root . --mode normal
```

The default `standard` config profile keeps every provider disabled and host-sensitive optional capabilities off. Repository maintainers can initialize the packaged development configuration explicitly:

```powershell
tinysoul init my-agent-dev --config-profile development
```

The development profile contains enabled provider/capability settings but no credentials and does not install optional distributions or host executables. After initialization, the selected configuration and the shared Home copy are owned entirely by that project.

To rebuild a dedicated development project after packaged Home or configuration changes, run this from the project's parent directory:

```powershell
tinysoul reset my-agent-dev
```

`tinysoul reset` defaults to the `development` profile. It requires an existing TinySoul project that is not running, preserves an existing regular `.env` file byte-for-byte, and replaces every other project entry, including Home, configs, Memory, runtime state, archives, and conversation data. It therefore also removes project-local additions such as `.git`; use it only for a disposable development project. Reset a standard project explicitly with `--config-profile standard`.

The source checkout is not itself an initialized TinySoul project. Keep runtime development and real-provider smoke tests in an external directory created by `tinysoul init`, and pass that directory through `--root` or `TINYSOUL_REAL_PROJECT_ROOT` as appropriate.

For one non-interactive turn:

```powershell
tinysoul start --root . --once "Summarize today's work"
```

The Action Catalog is versioned package data and is not copied into projects. Project configuration, Agent Home, Memory, runtime state, and archives remain project-owned.

## Development

```powershell
python -m pip install -e ".[dev]"
.\scripts\test.ps1
$env:TINYSOUL_PYTHON=(Get-Command python).Source
.\scripts\typecheck.ps1
```

`test.ps1` 运行完整本地 pytest suite，包括 wheel 构建与隔离安装验收；真实供应商和显式 opt-in 网络测试默认跳过。脚本将 pytest、系统临时文件和项目实例目录隔离到 `.local-test/`，成功后清理本次运行，失败时保留现场。

`typecheck.ps1` 使用同一 Python 环境运行 `ty`；等价的原始命令是 `python -m ty check --python (Get-Command python).Source`。发布资源验收不能由 editable install 替代。

Architecture and module contracts are documented under `docs/design/`; the active lifecycle execution plan is under `docs/analysis/`.
