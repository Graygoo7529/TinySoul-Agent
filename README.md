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

The source checkout is not itself an initialized TinySoul project. Keep runtime development and real-provider smoke tests in an external directory created by `tinysoul init`, and pass that directory through `--root` or `TINYSOUL_REAL_PROJECT_ROOT` as appropriate.

For one non-interactive turn:

```powershell
tinysoul start --root . --once "Summarize today's work"
```

The Action Catalog is versioned package data and is not copied into projects. Project configuration, Agent Home, Memory, runtime state, and archives remain project-owned.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests -q
$env:TINYSOUL_PYTHON=(Get-Command python).Source
.\scripts\typecheck.ps1
```

若 Windows 沙箱或用户目录 ACL 阻止 pytest 创建临时目录或项目实例锁，可将测试临时目录与锁目录放到被忽略的仓库路径：

```powershell
$test_root = Join-Path (Get-Location) (".pytest-local-tmp-" + [guid]::NewGuid().ToString("N"))
$local_app_data = Join-Path $test_root "local-app-data"
$pytest_root = Join-Path $test_root "pytest"
New-Item -ItemType Directory -Force $local_app_data | Out-Null
$previous_local_app_data = $env:LOCALAPPDATA
$env:LOCALAPPDATA = $local_app_data
try {
    python -m pytest tests -q --basetemp $pytest_root -p no:cacheprovider
} finally {
    if ($null -eq $previous_local_app_data) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $previous_local_app_data
    }
}
```

发布资源验收由 `tests/release/test_wheel.py` 负责；它会在测试内部构建 wheel、隔离安装并验证 `tinysoul init`，不由 editable install 替代。

Architecture and module contracts are documented under `docs/design/`; the active lifecycle execution plan is under `docs/analysis/`.
