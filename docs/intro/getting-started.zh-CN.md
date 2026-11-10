# TinySoul 启动指南

[项目介绍](../../README.md) · [English](getting-started.en.md)

TinySoul 的 Python 后端和桌面前端分别启动，可以运行在同一台机器，也可以由电脑上的前端连接独立主机。请先阅读项目介绍中的安全说明，在隔离的试验环境中使用。

## 1. 准备环境

| 运行内容 | 所需环境 |
| --- | --- |
| Python 后端 | [uv](https://docs.astral.sh/uv/getting-started/installation/)，由它安装 Python 3.13 和项目依赖 |
| 从源码运行桌面前端 | Node.js 22.12+、pnpm、Rust stable（含 Cargo），以及 [Tauri 系统依赖](https://v2.tauri.app/start/prerequisites/) |

Windows 桌面开发还需要 MSVC C++ Build Tools 和 WebView2；macOS、Linux 的系统依赖见上面的 Tauri 文档。只运行后端不需要 Node.js 或 Rust；只运行前端不需要安装 Python 后端。

克隆仓库后，除前端章节外，所有命令都在**仓库根目录**执行。无需 Conda，也无需手动激活虚拟环境：uv 根据 `.python-version` 创建仓库内的 `.venv`，根据 `uv.lock` 安装依赖。

```sh
uv python install
```

## 2. 安装后端并初始化数据目录

两种安装方式任选其一。下面统一用 `../my-agent` 保存配置、会话和文件；它与源码仓库分开，可以替换成自己的路径。初始化目标必须不存在或为空。

### 开发安装（适合持续修改源码）

```sh
uv sync --locked --extra dev
uv run --locked --extra dev tinysoul init ../my-agent
```

`dev` 包含测试、类型检查和可选能力的 Python 依赖；项目以 editable 方式安装。修改源码后**重启后端进程**即可生效，独立主机也可以采用这种安装方式。

### 标准安装（只需基础运行依赖）

```sh
uv sync --locked --no-editable
uv run --locked --no-editable tinysoul init ../my-agent
```

标准安装把当前代码安装到虚拟环境中。若需 MCP/ACP 或网页抓取，可分别添加 `--extra external-tools`、`--extra web-crawl`，并在后续 `sync`、`run` 中保持相同选项。外部服务或工具所需的程序仍需另行安装。

**安装方式与配置模板相互独立。** 上面两种方式都使用默认的 `standard` 配置模板。`init --config-profile development` 则使用维护者的开发配置，预先启用了部分供应商、能力和本地代理；使用前需要按自己的机器调整。`--extra dev` 并不要求使用这个模板。

## 3. 配置模型并启动

初始化后的数据目录中，常用文件是：

| 位置 | 用途 |
| --- | --- |
| `.env` | 后端环境配置、模型 API 凭据和监听地址 |
| `.auth` | `init` 生成的稳定登录 token，格式为 `token=...` |
| `configs/` | 模型、任务、能力等 TOML 配置 |
| `home/`、`memory/`、`runtime/`、`archive/` | 个人规约、记忆、活动数据和归档 |

`standard` 模板默认关闭模型供应商。开始对话前，在 `.env` 填入所选供应商要求的 API 凭据，在 `configs/llm/providers.toml` 启用它，并确认 `configs/llm/models/` 中的模型绑定和 `configs/llm/tasks.toml` 中的任务模型链对应可用模型。也可以启动后通过前端设置完成配置，保存后应用；手动修改文件后重启后端。详见 [LLM 配置设计](../design/llm.md)。

开发安装启动：

```sh
uv run --locked --extra dev tinysoul start --root ../my-agent --mode normal
```

标准安装启动：

```sh
uv run --locked --no-editable tinysoul start --root ../my-agent --mode normal
```

后端在终端中持续运行，同时提供前端连接入口。`--mode normal` 控制终端输出详略，可改为 `verbose` 或 `model`。只执行一次非交互任务时，可将它替换为 `--once "总结今天的工作"`；该模式不开放前端 Endpoint。

## 4. 启动前端并登录

另开一个终端，从仓库根目录进入前端目录：

```sh
cd visualization
pnpm install --frozen-lockfile
pnpm tauri dev
```

本地和远程使用同一种登录方式：输入后端地址与 token。本机默认地址是 `127.0.0.1:1430`，token 使用后端数据目录 `.auth` 中 **`token=` 后面的值**。缺少有效 `.auth` 时后端不会启动；正常重启不会更换 token。

前端会在本机记住地址和 token，下次打开自动连接；“退出登录”清除这份本地凭据，便于切换主机。关闭前端只断开连接，后端仍需保持运行。界面设置可以切换亮暗主题和中英文，偏好保存在所连接项目的后端。

在 `visualization/` 内，`pnpm tauri build` 构建桌面安装包；`pnpm dev` 只启动浏览器预览，无需 Rust，部分桌面功能会有所不同。更多前端开发与检查指令见 [前端说明](../../visualization/README.md)。

## 5. 连接独立主机

在主机的数据目录 `.env` 中配置监听地址，并重启后端：

```dotenv
TINYSOUL_ENDPOINT__BIND_HOST=0.0.0.0
TINYSOUL_ENDPOINT__PORT=1430
```

电脑前端填写主机可达的 IP，例如 `192.168.1.20:1430`，并使用该主机 `.auth` 的 token。`0.0.0.0` 表示后端监听所有网络接口，不是前端的连接地址。允许受信设备访问该端口，通过受信局域网或 VPN 连接，不要直接暴露到公网。

后端的 `.env`、`.auth`、TOML 和运行数据留在主机；电脑只保存登录信息。不要提交凭据文件。前端重连可以继续查看仍在运行的后端；它不表示后端进程退出后可以恢复未完成的 Turn。

## 6. 更新与检查

更新仓库源码后，开发安装执行 `uv sync --locked --extra dev` 并重启后端。标准安装执行 `uv sync --locked --no-editable --reinstall-package tinysoul` 后重启。前端依赖变化后重新执行 `pnpm install --frozen-lockfile`。

调整 Python 依赖声明后，执行 `uv lock` 并一并提交锁文件，再同步环境。换机器时重新创建 `.venv`，不要复制虚拟环境。源码更新不会自动覆盖已有数据目录中的配置与 Home。

后端开发检查：

```sh
uv run --locked --extra dev python scripts/test.py
uv run --locked --extra dev python scripts/test.py --suite full
uv run --locked --extra dev ty check
```

第一条默认运行 Fast；Full 包含本地集成和打包检查。代码修改完成前运行 Full 与类型检查。本地测试无需模型凭据，产物保存在忽略的 `.local-test/` 中；聚焦测试、外部测试与排错见 [测试说明](../../tests/README.md)。

### 仅在需要清空试验数据时 reset

停止目标后端，并在目标数据目录外执行：

```sh
uv run --locked --extra dev tinysoul reset ../my-agent --config-profile standard
```

**这会保留 `.env` 与 `.auth`，删除并重建其余全部内容**，包括配置、Home、Memory、会话、工作区、归档和目标目录中的 `.git`。这里显式选择 standard 模板；省略 `--config-profile` 时 reset 默认使用 development。reset 用于清空试验项目，不用于日常更新或数据迁移。
