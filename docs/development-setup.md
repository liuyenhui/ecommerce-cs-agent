# 本地开发环境说明

本文说明 `ecommerce-cs-agent` 当前本地开发入口、Python 环境、评测命令、运行时环境变量和开发前检查清单。它不是新的架构来源，只补充本地工程化入口；接口契约以 [OpenAPI Contract](openapi.yaml) 为准，部署环境以 [Deployment](deployment.md) 为准，开发范围以 [Development Readiness](development-readiness.md) 为准，项目总览见 [README](../README.md)。

## 1. 本地开发目标和当前状态

本地开发目标是让后端、Admin、评测和部署验证都能在同一套可复现命令下运行，并且与 k8s 无状态部署方式保持一致。

当前仓库已有 `evals/`，可以运行标准库实现的 live quick eval 和对应单元测试。但根目录当前没有正式的 `pyproject.toml` 或 `requirements.txt`，所以完整可复现的开发环境仍需后续补齐依赖清单、安装入口和 CI 对齐命令。

现阶段本地可依赖的内容：

- `evals/`：轻量 live eval 命令入口。
- `tests/evals/test_live_cli.py`：评测 CLI 的标准库单元测试。
- `docs/openapi.yaml`：第一版 API 合同。
- `docs/deployment.md`：dev 环境、Secret key 和 live eval 连接方式。

现阶段仍需补齐的内容：

- Python 项目的正式依赖文件和安装入口。
- 业务 API 的本地启动入口。
- Admin Web / Admin API 的本地启动入口。
- 数据库迁移、初始化数据和本地服务编排命令。

## 2. Python 版本

交付口径与项目技术文档对齐，推荐使用 Python 3.12。

本机可能同时安装了 Python 3.13，也可能已有 Python 3.13 生成的缓存文件；这些只能说明本机曾用 Python 3.13 运行过命令，不改变项目交付口径。后续依赖、测试、CI 和镜像构建应以 Python 3.12 为准。

检查版本：

```bash
python3.12 --version
```

## 3. 虚拟环境

建议在仓库根目录创建 `.venv`：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

激活后，`python` 应指向 `.venv` 内的 Python 3.12。

## 4. 依赖安装

当前根目录没有正式依赖文件时，不应假设可以完整安装业务应用。此阶段只能运行不依赖第三方包的标准库 eval 工具和对应测试。

当前可执行：

```bash
python -m evals.cli --help
python -m unittest tests.evals.test_live_cli -v
```

后续补齐 Python 项目文件后，按项目实际形态选择安装方式：

```bash
pip install -e .
```

或：

```bash
pip install -r requirements.txt
```

补依赖清单时需要同步更新 CI、本地开发说明、镜像构建和测试命令，避免本机环境与交付环境漂移。

## 5. 本地运行评测

查看 CLI 帮助：

```bash
python -m evals.cli --help
```

运行评测 CLI 单元测试：

```bash
python -m unittest tests.evals.test_live_cli -v
```

## 6. Live Eval

Live eval 面向已经启动或已部署的 Agent API。命令通过环境变量读取目标地址和 API token，不应打印 token，也不要把 token 写进 shell 历史、文档或日志。

```bash
export TARGET_BASE_URL=<from-secret>
export AGENT_API_TOKEN=<from-secret>
python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

说明：

- `TARGET_BASE_URL` 指向待测 API 根地址。
- `AGENT_API_TOKEN` 只从本地安全来源、GitHub Secrets、K8s Secrets 或外部 Secret Manager 获取。
- CLI 会读取 `AGENT_API_TOKEN` 并发送 Bearer token，但测试输出不应包含 token 或完整 `Authorization` header。

## 7. 本地 API / Admin 启动状态

业务 API 源码和启动命令尚未在仓库形成可复现入口。后续实现 FastAPI 服务时，必须在本文补充：

- 本地安装依赖命令。
- 数据库迁移命令。
- API 启动命令。
- `/health` 验证命令。
- `POST /v1/reply-decisions` 本地最小验证命令。

Admin Web / Admin API 的本地启动命令也尚未在仓库形成可复现入口。后续实现时，必须在本文补充：

- 前端依赖安装命令。
- Admin 本地启动命令。
- 登录和 session 相关本地配置。
- Admin `/health` 或页面访问验证命令。

在这些入口补齐前，不应把临时本机命令当成团队交付口径。

## 8. 环境变量分类

本节只记录 key 和来源占位，不记录真实值。真实 Secret 只能保存在 GitHub Secrets、Kubernetes Secrets 或批准的外部 Secret Manager。

### 8.1 数据库

```bash
DATABASE_URL=<from-secret>
```

### 8.2 对象存储

```bash
OBJECT_STORAGE_ENDPOINT=<from-secret>
OBJECT_STORAGE_BUCKET=<from-secret>
OBJECT_STORAGE_REGION=<from-secret>
OBJECT_STORAGE_ACCESS_KEY_ID=<from-secret>
OBJECT_STORAGE_SECRET_ACCESS_KEY=<from-secret>
OBJECT_STORAGE_PATH_STYLE=<from-secret>
```

### 8.3 LLM

```bash
LLM_BASE_URL=<from-secret>
LLM_MODEL=<from-secret>
```

如果后续需要模型 API key，只能以 Secret 注入，不写入仓库。

### 8.4 外部 Agent API 鉴权

```bash
AGENT_API_TOKEN=<from-secret>
```

### 8.5 Admin / Session

```bash
SESSION_SECRET=<from-secret>
JWT_SECRET=<from-secret>
```

## 9. Secret 和 `.env` 规则

- `.env` 禁止提交。
- 不要把真实 token、数据库密码、对象存储密钥、LLM key、session secret、JWT secret、私钥或生产客户数据写进 Git、文档、Issue、PR、聊天记录或日志。
- 文档中只允许写 Secret key 名、K8s Secret 名、GitHub Secret 名和 `<from-secret>` 这类占位值。
- 本地调试需要 `.env` 时，只能保留在本机，并确保 `.gitignore` 和提交前检查不会放行它。
- 运行 live eval 时不要 `echo "$AGENT_API_TOKEN"`，不要提交 shell 历史片段或包含 token 的截图。

## 10. 开发前检查清单

- 已确认使用 Python 3.12 虚拟环境。
- 已激活 `.venv`，且 `python --version` 与交付口径一致。
- 已确认当前阶段是否存在 `pyproject.toml` 或 `requirements.txt`；不存在时只运行标准库 eval 工具。
- 已运行 `python -m evals.cli --help` 确认 CLI 可加载。
- 已运行 `python -m unittest tests.evals.test_live_cli -v` 确认 live eval CLI 行为稳定。
- 需要 live eval 时，已从安全来源设置 `TARGET_BASE_URL` 和 `AGENT_API_TOKEN`，且没有打印 token。
- 需要改 API 时，已先核对 [OpenAPI Contract](openapi.yaml)。
- 需要改部署或 Secret key 时，已先核对 [Deployment](deployment.md)。
- 需要判断第一版范围时，已先核对 [Development Readiness](development-readiness.md)。
- 提交前已确认 `.env`、真实 Secret、生产客户数据、含 token 的日志或截图没有进入 Git。
