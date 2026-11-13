# 合同智能审查

React + TypeScript 合同工作台，配套 FastAPI API、后台审查 worker 和 ONLYOFFICE 正文编辑接入。

支持 DOCX 导入与版本保存、规则审查、责任事项识别、增量审查意见、正文定位、人工处理和定稿。当前默认执行口径为 `review-events-v2`，结果格式为 `interactive-review-v3`。审查结果需人工复核。

## 仓库范围

公开仓库包含应用代码、规则配置、合成测试文档、工程构造场景和相应工程验证记录。真实合同、历史法务案例、个案参数、业务截图、运行数据库和密钥配置不在仓库中。

没有安装历史案例资料时，规则页正常展示规则及工程构造案例，不生成历史案例。个案参数文件缺失时不启用个案指导。依赖真实合同的专项回归留在本地，不属于本仓库的工程测试集。

ONLYOFFICE Document Server 及本项目适配的编辑器桥接是独立部署依赖，不包含在本仓库。当前接入需要匹配的定制构建；不能仅启动普通官方镜像就假定全部联动功能可用，见 [ONLYOFFICE 接入](docs/ONLYOFFICE-INTEGRATION.md)。

## 目录

- `frontend/`：工作台、审阅室、规则页面、编辑器桥接客户端和前端测试。
- `backend/app/`：合同 API、文档版本、模型审查、任务队列和过程事件。
- `backend/tests/`：工程测试及明确标注的合成 DOCX 样本。
- `backend/evaluation/`：工程构造数据、评测脚本及记录；不代表真实合同准确率。
- `analysis/legal-corpus/draft-v0.1/`：规则配置及执行口径确认记录，不包含原始合同。

## 本地启动

需要 Python 3.12+、uv、Node.js 和 npm。

```sh
uv sync --directory backend --locked
cp backend/.env.example backend/.env
npm --prefix frontend ci
```

在 `backend/.env` 配置模型网关和密钥。模型客户端只读取该文件中的模型配置；其余 `RIXIN_*` 配置通过进程环境变量设置。

分别启动 API、worker 和前端：

```sh
RIXIN_INTERACTIVE_REVIEW=1 uv run --directory backend uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8010
```

```sh
RIXIN_INTERACTIVE_REVIEW=1 uv run --directory backend python -m app.worker
```

```sh
npm --prefix frontend run dev -- --port 5174
```

访问 `http://127.0.0.1:5174/`。API 健康检查为 `http://127.0.0.1:8010/health`。默认前端将 `/api` 转发到 `8010`，可用 `RIXIN_API_TARGET` 修改。正文编辑还需按接入文档配置 ONLYOFFICE；未配置时会明确显示编辑服务不可用。

默认数据库为 `backend/data/review.sqlite3`，初始化时自动执行迁移。可通过 `RIXIN_DB` 指定路径；API 与 worker 必须使用同一数据库和相同版本代码。新建数据库不包含业务合同或演示合同。

## 动态审查

任务发现、开始、完成及失败写入持久化事件；通过证据校验的意见陆续展示，最终以本轮汇总结果为准。SSE 失败时回退游标轮询，刷新页面可从快照恢复。

运行中可以阅读意见及点击定位。定位不触发保存，正文或材料变化后会阻止使用过期结果处理和定稿。自动跟随、自动写回批注/修订和正文临时标记未启用。

- `VITE_LIVE_REVIEW=0`：关闭细粒度任务和增量意见展示。
- `VITE_REVIEW_SSE=0`：关闭 SSE，使用轮询。

以上前端变量在 Vite 启动或构建时设置。审查执行版本哈希不匹配的旧排队任务会明确失败，需要重新发起，不会绕过校验执行。

## 测试与构建

```sh
uv run --directory backend pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

测试不需要真实合同、运行数据库或模型密钥。前端生产产物位于 `frontend/dist/`。开发验证页 `onlyoffice-integration.html` 只接受测试合同，不进入生产构建。

## 当前边界

当前采用本地开发模式和单写编辑会话，账号权限与多人协作尚未接入。PDF/OCR 未接入。规则、案例和工程验证记录均保留适用范围及确认状态，不能把工程测试通过视为法律准确率。
