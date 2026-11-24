# 合同智能审查

React + TypeScript 合同工作台，配套 FastAPI API、后台审查 worker 和 ONLYOFFICE 正文编辑接入。

支持 DOCX 导入与版本保存、规则审查、责任事项识别、增量审查意见、正文定位、人工处理和可选的审阅完成记录。当前执行口径为 `review-configured-rules-v1`，结果格式为 `interactive-review-v3`。审查结果需人工复核。

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
npm --prefix frontend run dev
```

访问 `http://127.0.0.1:9174/`。前端固定使用端口 `9174`，端口被占用时直接报错，避免自动换端口导致认证回调地址不一致。API 健康检查为 `http://127.0.0.1:8010/health`。默认前端将 `/api` 转发到 `8010`，可用 `RIXIN_API_TARGET` 修改。正文编辑还需按接入文档配置 ONLYOFFICE；未配置时会明确显示编辑服务不可用。

统一登录入口为 `http://127.0.0.1:9174/`，回调为 `/callback`。API 默认开启 OIDC 验签与角色、合同归属校验；历史无归属合同仅管理员可见。接入配置和验收说明见 [统一身份认证](docs/IDENTITY-INTEGRATION.md)。

默认数据库为 `backend/data/review.sqlite3`，初始化时自动执行迁移。可通过 `RIXIN_DB` 指定路径；API 与 worker 必须使用同一数据库和相同版本代码。新建数据库不包含业务合同或演示合同。

## 动态审查

新任务默认使用 `review-configured-rules-v1`，只执行规则中心当前列出的 `RL-01` 至 `RL-05` 和 `VL-01`。规则在入队时固化，意见可追溯到本轮规则和原文。项目责任口径未确认时显示待核实。历史任务仍可查看原执行版本。

当前默认模式从本轮合同、我方立场及配置规则生成条款意见，再依据意见和原文拟稿。一条意见最多对应一份改文；服务端校验原文定位、数值和编辑范围。个案历史批注和预写改文不参与此模式。

API 和 worker 使用同一版本代码。旧批次可查看原结果。旧策略或实现版本变更后的失败任务通过重试创建关联批次，按现行配置执行。

规则核查完成后逐项显示意见，拟稿时在对应卡片更新进度和结果。核查或拟稿失败的项目保留未完成标识。

审查卡片按风险概述、修改方案、具体修订分层。当前条款结果按审查原文的段落及段内位置排列，同组风险保持阅读顺序；修改建议按实际修改位置排列，共享方案只展示一次，无法定位的事项置后。原文引用通过校验后才显示定位入口。修订使用单段增删对比，可切换修改后全文；每处修改独立定位、复制，过期、冲突和未通过校验的建议不可复制。当前复制不会写入 OnlyOffice，人工处理记录也不代表正文已修改。

阶段进度、核查意见和失败信息写入持久化事件。局部拟稿完成后校验引用和修改范围，再展示候选稿。SSE 断线后自动重连，并按游标补读事件。刷新页面可从快照恢复。

运行中可以阅读意见及主动点击已验证的原文引用。正文不自动跳转、不模拟逐段阅读；审查期间正文只读，结束后恢复修订编辑。右侧在底部时跟随新内容，向上滚动或选中文字时保持阅读位置，并提示回到最新位置。主动定位会先确认保存，并将历史引用迁移到可确认的当前原文。修改正文后可继续处理已有意见，无需重新审查。可选的“标记本轮审阅完成”会保存当前正文版本、原审查快照和处理记录，不要求清空待办或填写结论，也不会锁定正文或禁止继续处理意见。材料或审查主体变化仍需更新审查结果。候选修改不会自动写回正文。

- `VITE_LIVE_REVIEW=0`：关闭细粒度任务和增量意见展示。
- `VITE_REVIEW_SSE=0`：关闭 SSE，使用轮询。
- worker 进程环境 `RIXIN_REVIEW_STREAM=0`：关闭模型文本流式输出，保留每项校验完成后的增量展示。

以上前端变量在 Vite 启动或构建时设置。审查执行版本哈希不匹配的旧排队任务会明确失败，可通过重试创建关联的新批次。

## 测试与构建

```sh
uv run --directory backend pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

工程测试不需要运行数据库或模型密钥；`test_wuwei_edit_alignment.py` 是依赖本地原稿与人审稿的私有验收，未提供材料时需单独排除并注明未验证。前端生产产物位于 `frontend/dist/`。开发验证页 `onlyoffice-integration.html` 只接受测试合同，不进入生产构建。

## 当前边界

当前采用本地开发模式和单写编辑会话，已接入公司统一身份认证，尚未实现多人协作编辑。PDF/OCR 未接入。规则、案例和工程验证记录均保留适用范围及确认状态，不能把工程测试通过视为法律准确率。

配置规则核查与人工处理分别记录。模型调用检查点支持恢复未完成任务。后台默认同时审查 3 份不同合同，超出的任务自动排队。有空位时优先领取最早可执行的任务，同一合同的不同轮次依次执行。启动 worker 时可用 `RIXIN_REVIEW_JOB_CONCURRENCY` 调整合同并发数。

单个 worker 的全部审查任务共用模型调用上限，由 `RIXIN_REVIEW_MODEL_CONCURRENCY` 设置，默认 8。单份合同内部由 `RIXIN_REVIEW_CONCURRENCY` 配置规则执行线程数，默认 8，范围 1–8。局部拟稿分组最多同时运行 2 组。详见 [配置规则修订](docs/COORDINATED-REVISIONS.md)。
