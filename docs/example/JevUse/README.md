# Jev 使用说明

这一目录面向实际调用 TypeSafe Jev API 的开发与实验。建议按以下顺序阅读：

1. [核心概念与整体说明](./06_核心概念与整体说明.md)：用一条主线解释 Jev 的定位、一次调用、能力边界，以及 JevKG/JevSession 的系统位置。
2. [基础调用说明](./01_基础调用说明.md)：请求结构、三种问题类型、Python/JavaScript/HTTP 示例。
3. [进阶使用与工程注意事项](./02_进阶使用与工程注意事项.md)：问题拆分、概率与置信度、错误处理、重试、成本和安全边界。
4. [Python SDK：用途与采用建议](./05_Python_SDK.md)：官方 SDK 的同步/异步调用、类型、重试和采用建议。
5. [案例与实验记录](./03_案例与实验记录.md)：本项目的支持工单、知识图谱和 Agent 会话案例，以及真实 API 调用结果的记录方式。

## 可运行示例

```text
examples/
├── jev_client.py       # 标准库 HTTP 客户端，自动读取项目根目录 .env
├── run_cases.py        # 三个案例：工单、KG 边验证、Agent 会话门控
└── README.md
```

在项目根目录 `.env` 中设置 `TYPESAFE_API_KEY` 后运行：

```powershell
python 01_JevUse/examples/run_cases.py --case support
python 01_JevUse/examples/run_cases.py --case kg
python 01_JevUse/examples/run_cases.py --case session
```

示例默认只打印脱敏后的答案和 token 用量；完整响应可以通过 `--save` 保存到 `01_JevUse/results/`，该目录已被 `.gitignore` 忽略。

## 官方资料

- [Introduction](https://docs.typesafe.ai/introduction)
- [Quick start](https://docs.typesafe.ai/introduction/quickstart)
- [API reference](https://docs.typesafe.ai/api)
- [Python SDK](https://docs.typesafe.ai/sdk/python)
- [JavaScript SDK](https://docs.typesafe.ai/sdk/javascript)
- [Primitives: Choice](https://docs.typesafe.ai/primitives/choice)
- [Primitives: Score](https://docs.typesafe.ai/primitives/score)
- [Primitives: Noul](https://docs.typesafe.ai/primitives/noul)
- [Confidence](https://docs.typesafe.ai/confidence)
- [逐页官方文档阅读记录](./04_官方文档逐页阅读记录.md)
- [Python SDK：用途与采用建议](./05_Python_SDK.md)
- [核心概念与整体说明](./06_核心概念与整体说明.md)
