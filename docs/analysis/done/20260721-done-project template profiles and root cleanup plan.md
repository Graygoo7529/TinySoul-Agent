# 20260721 Project Template Profiles And Root Cleanup Plan

status: done

## 意图

将源码仓库与可运行 TinySoul 项目彻底分离。`tinysoul/assets/project` 成为 `tinysoul init` 唯一模板事实源；仓库根不再保存第二份 configs/Home 或运行期状态。初始化模板由唯一公共项目内容和两套完整配置 profile 组成，不为 Home 建立 profile 分支。

## 已确认语义

1. `tinysoul init [DIRECTORY]` 默认使用 `standard` config profile，并可通过 `--config-profile development` 显式选择开发配置；不增加 `--provider`。
2. 公共模板只维护一份 README、`.gitignore`、`tinysoul.toml` 与 Home。profile 分别提供完整 `configs/` 和与之匹配的 `.env.example`，初始化后仍物化为普通项目结构，不保存 profile marker，不改变 Infra 配置优先级。
3. standard 延续当前安全模板：全部 LLM provider disabled，Shell、Kimi Search、Discovery 和 Defuddle 默认关闭。
4. development 复制当前根项目的非敏感配置，包括 provider/capability enabled 状态、模型顺序、`sublyx_proxy` 端点身份和对应 `.env.example` 变量名；实际 `.env`、密钥、runtime、archive 不进入 wheel。
5. development 只选择配置，不安装 Crawlee、Defuddle executable 或凭据；缺少已启用能力的依赖/凭据时继续由现有模块配置边界明确失败。
6. 生成后 configs/Home 完全归项目所有，后续 package template 更新不自动修改已有项目。
7. 根 `.env` 删除，不迁入 `reference/old_dev`；根 configs、Home、`tinysoul.toml`、`.env.example`、runtime 与 archive 移入已忽略的 `reference/old_dev`，不再追踪。

## 目标资源布局

```text
tinysoul/assets/project/
  README.md
  .gitignore
  tinysoul.toml
  home/
  config_profiles/
    standard/
      .env.example
      configs/
    development/
      .env.example
      configs/
```

初始化输出不包含 `config_profiles/`，只包含 README、`.gitignore`、`.env.example`、`tinysoul.toml`、所选 `configs/`、共享 `home/` 和初始化器建立的空 `memory/`。

## 实施项

### Stage 1：模板资源与初始化契约

status: done

- 新增稳定 `ProjectConfigProfile`，只接受 `standard` 与 `development`。
- `ProjectInitializer` 确定性合成公共资源和所选 profile，拒绝缺失/空 profile、非法资源与相对路径冲突。
- `ProjectInitializationOutcome` 记录所选 profile；CLI 新增 `--config-profile` 并输出选择结果。
- 更新 setuptools package-data，确保共享 Home 与两套 profile 都进入 wheel。

### Stage 2：根项目迁移与文档

status: done

- 将现有安全模板配置移动为 standard profile，将根 configs 与 `.env.example` 复制为 development profile，Home 只保留当前共同内容。
- 将旧根项目非敏感内容与运行数据移入 `reference/old_dev`，删除根 `.env`。
- 增加根路径 ignore，防止重新形成第二份项目模板。
- 更新 AGENT、App/Infra 设计、仓库 README 和项目模板 README，说明 profile 仅属于初始化期物化。

### Stage 3：测试去根项目化

status: done

- App 测试通过 `ProjectInitializer` 创建临时项目，不再从 `Path.cwd()` 读取根配置。
- LLM/Shell 配置测试分别验证 standard 与 development profile；真实 provider/Web 测试要求显式外部项目根。
- initializer 测试覆盖默认 standard、显式 development、共同 Home、完整 config 文件集合、非空目标拒绝和标准未配置 provider 失败。
- wheel clean-source/隔离安装测试覆盖两套 profile、共享 README/Home、无内部 profile 目录泄漏和两种 init。

### Stage 4：验证与关闭

status: done

- 审计源码与测试不存在对根 configs/Home/`.env`/`tinysoul.toml` 的运行依赖。
- 运行全量 pytest、ty 类型检查、wheel 隔离验收与必要的 CLI init smoke。
- 全部通过后将各 Stage 和本文状态标记 done，并按规则重命名为 `20260721-done-project template profiles and root cleanup plan.md`。

## 实施结果

- `ProjectConfigProfile`、initializer 与 CLI 已形成稳定的 standard/development 初始化契约；生成项目只包含所选普通 `configs/`/`.env.example`、共享资源和空 `memory/`，不泄漏内部 profile 布局。
- development profile 与迁移前根 configs/`.env.example` 共 20 个文件逐字节一致；standard 延续安全模板。共享模板 Home 与迁移前根 Home 的 18 个文件逐字节一致，两种初始化结果的 Home 和 config 文件形状测试一致。
- 根 configs、Home、`tinysoul.toml`、`.env.example`、runtime 与 archive 已迁入忽略的 `reference/old_dev`，根 `.env` 已删除且未迁移；源码根路径已加入 ignore，测试与真实供应商 smoke 不再读取根项目配置。
- package-data、wheel clean-source 构建、隔离安装和两种 profile 初始化均通过；全量 pytest、ty 类型检查和根目录运行态残留审计通过。

## 非目标

- 不为已有项目提供 profile 切换或自动迁移命令。
- 不让 ConfigEnvironment 识别 profile，不增加新的运行时配置层。
- 不把 Home、Action Catalog、密钥、runtime 或 archive 放入 config profile。
- 不让 development profile 绕过 capability dependency、credential 或 host executable 校验。
