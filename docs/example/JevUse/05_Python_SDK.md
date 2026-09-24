# 官方 Python SDK：用途与采用建议

核查日期：2026-09-23。官方文档入口为 [Client SDKs](https://docs.typesafe.ai/sdk)、[Python SDK](https://docs.typesafe.ai/sdk/python) 和 [Python SDK Usage](https://docs.typesafe.ai/sdk/python/usage)。

## SDK 解决什么问题

SDK 不是另一个模型，也不会把 Jev 下载到本地。它是对同一个 TypeSafe HTTP API 的 Python 客户端封装，主要提供：

- `TypeSafeClient` 与 `AsyncTypeSafeClient`，适合同步脚本、Web 服务和高并发异步流程；
- `Choice`、`Score`、`Noul` 问题对象和对应答案类型，减少手写请求字典；
- 从 `TYPESAFE_API_KEY`、`TYPESAFE_BASE_URL`、`TYPESAFE_DEFAULT_MODEL` 读取配置；
- 默认 HTTP 超时、连接管理、重试策略和 `Retry-After` 处理；
- 按状态分类的异常、`request_id`、响应校验和 token 用量；
- `models.list()` 查看可用模型；
- `response_model` 将答案映射到 Pydantic 或 `SystemOneResponse` 子类；
- `base_url`、`extra_body` 和原始 question 字典，用于兼容网关或 API 新字段。

官方 JavaScript SDK 还提供 TypeScript 类型推断、ESM/CommonJS 支持；本项目当前以 Python 为主，暂不引入 Node 依赖。

## 何时值得使用

对一次性 HTTP 调用，现有标准库客户端更透明，便于核对 wire protocol。对持续开发、异步服务、重试、结构化响应和多团队协作，SDK 更适合。建议项目采用“双轨”：保留一个最小 HTTP 示例做协议基线，业务代码使用官方 SDK。

## 安装方式

用户可以选择项目约定的 conda 环境：

```powershell
conda env create -f environment.yml
conda activate jev
python -m pip show typesafe-sdk
```

若环境已存在：

```powershell
conda activate jev
python -m pip install -r requirements.txt
```

当前没有替用户创建 conda 环境，也没有向共享 `common` 环境安装包。安装完成后再运行本页的 SDK 示例。

## 同步与异步调用

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

with TypeSafeClient() as client:
    result = client.system_one(
        state={"message": "I was charged twice. Please fix this ASAP."},
        questions={
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(
                instructions="What is the customer's tone?",
                criteria={"calm": None, "frustrated": None, "angry": None},
            ),
            "urgency": Score(
                instructions="How urgent is this ticket?",
                criteria=["can wait", "this week", "today"],
            ),
        },
    )

print(result.nouls["billing"].noul)
print(result.choices["tone"].choice)
print(result.scores["urgency"].score)
print(result.request_id)
```

异步服务使用 `async with AsyncTypeSafeClient() as client` 和 `await client.system_one(...)`。显式传入的参数优先于环境变量；`TypeSafeClient(model="jev-1.13")` 可以固定模型别名或版本。

## 重试、错误和日志

```python
from typesafe_sdk import RetryPolicy, TypeSafeAPIError, TypeSafeClient

retry = RetryPolicy(max_retries=3, backoff_initial=0.5, backoff_max=5.0)

try:
    with TypeSafeClient(retry=retry, timeout=10.0) as client:
        result = client.system_one(state, questions)
except TypeSafeAPIError as error:
    print(error.status, error.request_id)
```

官方 Python SDK 的 RetryPolicy 默认会处理连接/超时以及常见 `408`、`429` 和 `5xx`。不可重复的外部动作不能放在 API 调用的自动重试副作用里；应先拿到决策，再由幂等业务代码执行。

SDK 日志使用 `typesafe_sdk` logger，也可用 `TYPESAFE_LOG_LEVEL=info|debug|warning|error|off`。文档说明认证等秘密 header 会脱敏，但 request/response body 不会自动脱敏，因此生产环境不能在 debug 日志中发送敏感 state。

## 类型化响应与兼容性

```python
from typesafe_sdk import Noul, NoulAnswer, SystemOneResponse, TypeSafeClient

class BillingResponse(SystemOneResponse):
    billing: NoulAnswer

with TypeSafeClient() as client:
    result = client.system_one(
        "I was charged twice.",
        {"billing": Noul(instructions="Is this about billing?")},
        response_model=BillingResponse,
    )
    assert result.billing == result.nouls["billing"]
```

`extra_body` 和 raw question dictionary 是官方提供的前向兼容出口，但只能发送 API 已支持的字段。未知 answer kind 会被 SDK 跳过；需要审计完整响应时读取 `raw_http_response`。

`client.models.list()` 是只读模型发现接口，可用于启动时检查账号可见的别名；生产日志仍应记录每次推理响应中的实际版本 ID，因为别名会随发布移动。

## 本项目采用结论

建议：

1. `01_JevUse/examples/jev_client.py` 保留为零依赖 HTTP 参考实现；
2. conda `jev` 环境建立后，增加 SDK 实现并用同一组 fixtures 对比 HTTP/SDK 的答案、request id、重试和耗时；
3. 所有业务调用固定 `response_model` 或显式检查答案类型，低置信度和异常走安全降级；
4. 不在 SDK debug 日志中记录原始会话、凭据或个人数据。

## 官方来源

- [Python SDK](https://docs.typesafe.ai/sdk/python)
- [Usage](https://docs.typesafe.ai/sdk/python/usage)
- [Synchronous client](https://docs.typesafe.ai/sdk/python/api/clients/sync)
- [Asynchronous client](https://docs.typesafe.ai/sdk/python/api/clients/async)
- [Retries](https://docs.typesafe.ai/sdk/python/api/retries)
- [Exceptions](https://docs.typesafe.ai/sdk/python/api/exceptions)
- [Constants](https://docs.typesafe.ai/sdk/python/api/constants)
