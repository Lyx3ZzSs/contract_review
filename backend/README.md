# 合同审查后端

FastAPI API 与独立 SQLite 任务 worker。安装、启动和工程测试见[项目说明](../README.md)。

- `app.main:create_app` 创建 API，`python -m app.worker` 消费审查任务。
- 模型配置来自 `backend/.env` 或进程环境变量，示例为 `.env.example`。
- `RIXIN_DB` 指定数据库路径；缺省为 `backend/data/review.sqlite3`。
- API 与 worker 使用相同配置和代码版本。数据库启动时自动迁移，现有记录不重算。
- `RIXIN_INTERACTIVE_REVIEW=1` 开启资料包入口；`RIXIN_REVIEW_POLICY` 可显式选择支持的执行版本。

`GET /health` 返回运行与模型配置状态；`GET /openapi.json` 返回接口定义。

审查接口包括合同、文档版本、资料包、审查运行及人工处理记录。`/api/v1/runs/{run_id}/execution-state` 返回过程快照，`execution-events` 按游标补读，`execution-stream` 提供 SSE。事件按 run/attempt 隔离，最终结果与终态事件在同一事务提交。

`tests/fixtures/` 中的合同文件和规则场景均为工程构造。公开仓库不附带历史合同语料，`tests/test_private_*.py` 及指定的合同专项回归文件只在本地保留。缺少历史案例时规则页继续展示已收录的工程案例；已有资料损坏时仍报错，不将损坏伪装成空结果。

本地可选的 `backend/policies/case-parameters.json` 用于明确绑定文档、角色和阶段的个案参数。该文件不入库，缺失时不启用个案指导，不把历史意见推广为公司通用政策。
