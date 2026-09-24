# Jev 示例

要求 Python 3.10+。示例只使用 Python 标准库，不需要安装 SDK；它直接调用官方 `POST /v1/systemone` 接口，方便观察原始请求和响应。

```powershell
python 01_JevUse/examples/run_cases.py --case support
python 01_JevUse/examples/run_cases.py --case kg --save
```

脚本从当前目录向上查找项目根目录 `.env`，读取 `TYPESAFE_API_KEY`、`TYPESAFE_MODEL` 和 `TYPESAFE_ENDPOINT`。请不要把响应文件或 key 提交到 Git。

安装 `requirements.txt` 后，也可以验证官方 SDK：

```powershell
.\.venv\Scripts\python.exe 01_JevUse/examples/sdk_call.py
```
