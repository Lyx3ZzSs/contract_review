# 合同审查后端

FastAPI API 与独立 SQLite 任务 worker。安装、启动和工程测试见[项目说明](../README.md)。

- `app.main:create_app` 创建 API，`python -m app.worker` 消费审查任务。
- 模型配置来自 `backend/.env` 或进程环境变量，示例为 `.env.example`。
- `RIXIN_DB` 指定数据库路径；缺省为 `backend/data/review.sqlite3`。
- API 与 worker 使用相同配置和代码版本。数据库启动时自动迁移，现有记录不重算。
- `RIXIN_INTERACTIVE_REVIEW=1` 开启资料包入口。新任务使用 `review-configured-rules-v1`。若部署环境设置了旧版 `RIXIN_REVIEW_POLICY`，请移除该旧配置。

`GET /health` 返回运行与模型配置状态；`GET /openapi.json` 返回接口定义。

审查接口包括合同、文档版本、资料包、审查运行及人工处理记录。`/api/v1/runs/{run_id}/execution-state` 返回过程快照，`execution-events` 按游标补读，`execution-stream` 提供 SSE。事件按 run/attempt 隔离，最终结果与终态事件在同一事务提交。

`tests/fixtures/` 中的合同文件和规则场景均为工程构造。公开仓库不附带历史合同语料，`tests/test_private_*.py` 及指定的合同专项回归文件只在本地保留。缺少历史案例时规则页继续展示已收录的工程案例；已有资料损坏时仍报错，不将损坏伪装成空结果。

## DOC 上传

合同上传与主体识别支持 DOC、DOCX（最大 20 MB）。DOC 在 API 所在机器上经 LibreOffice 转换为 DOCX，随后进入既有解析、审查与 OnlyOffice 流程；编辑和导出格式为 DOCX。原始 DOC 字节和标准化结果保存在 `document_conversions`，以原始文件 SHA-256 复用转换结果，确保预览确认、正式导入与重试使用同一份文档。转换出处同时记录于版本解析信息 `source_document`。

API 主机需要安装 LibreOffice；程序默认从 PATH 查找 `soffice` / `libreoffice`，macOS 也查找标准应用路径。可用 `RIXIN_SOFFICE_PATH` 指定可执行文件。每次转换使用隔离临时目录、独立配置、60 秒超时；仅转换成功且正文可解析后入库。无转换程序返回 503，损坏、加密或不可读文件返回 422，超出文件限制返回 413。DOCX 不依赖转换程序。

转换保真度取决于原文件。用户应核对复杂表格、自动编号、批注和修订，不能保证所有旧 Word 特性完全保留。参考 [LibreOffice 命令行参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)。

## 天眼查主体审查

凭证由服务端 `TIANYANCHA_TOKEN` 读取；`TIANYANCHA_API_URL` 使用 `https://open.api.tianyancha.com`。本地 `.env` 不入库，浏览器不接触 Token。

当前接入基本信息（1116）、股东（821）、企业属性（1154）、企业规模（1149），以及失信人（843）、被执行人（839）、严重违法（846）、经营异常（848）、税务非正常户（1178）、破产重整（1036）和破产重整详情（1037）。接口地址、参数和字段以官方公开元数据为依据：`https://open.tianyancha.com/open-admin/interface/uni.json?id={接口编号}`，2026-11-18 核对。

- `GET/POST /api/v1/contracts/{cid}/subjects` 读取当前正文版本的核查记录或核对企业身份；名称不一致必须人工确认，随后才能查询风险。
- `POST /api/v1/subject-checks/{id}/modules/{module}?page=1&refresh=false` 查询单项；列表每页 20 条，按顺序翻页。`refresh=true` 从第一页重新查询，成功后清除旧分页及案件详情。
- `POST /api/v1/subject-checks/{id}/bankruptcy/{case_id}` 只允许查询已返回案件的详情，使用列表返回的企业 ID 和案件 UUID。
- 前端“查询主体/补全查询”逐项查询并保存 6 类风险和 3 项扩展信息，单项失败不阻止后续项目。切走页面时停止发起后续请求，已返回结果保留；再次补全复用 24 小时内成功结果。
- 明确区分 `not_queried / ready / empty / unavailable / failed`。只有业务码 `300000` 或结构正确且总数为 0 的成功响应表示未发现记录；权限、额度、网络及结构错误不能转换成零记录。破产重整的 `status` 为 0 时标注历史案件，1 时标注当前案件。
- 记录与合同、正文版本绑定；正文版本过期返回 409。完整审查意见书固定导出时的核查数据、查询时间、已加载/总条数、明细及权限/失败状态，后续更新不改写已生成文件。

2026-11-18 联调：基本信息、股东、规模、5 类风险以及破产详情返回有效业务响应；所配置账号的税务非正常户（1178）及企业属性（1154）返回 `300005`，需要账号管理员开通对应权限后重试。技术接入不会自动购买接口权限。

### 违约责任限额

配置规则审查执行 VL-01。会议试算的税率、计价基数和比例维护在 `app/liability-limits.json`。每次审查保存规则快照，供应方身份、开票税率、计价基数和可叠加责任从本次正文及可读附件提取。责任金额及适用上限由服务端计算。

运管已确认适用的项目可在 `policies/liability-confirmations.json` 以合同 ID 登记依据和生效日期。未登记时结果保留为待核对。以下为配置结构示例，示例合同 ID 和来源需替换为实际值。

```json
{
  "合同ID": {
    "source": "运管确认记录编号",
    "effective_from": "2026-11-20",
    "supplier_bands": {
      "6": {"basis": "annual_fee", "percent": 10},
      "13": {"basis": "contract_total", "percent": 30}
    }
  }
}
```

`effective_until` 可填写最后有效日期。如果运管已明确某口径覆盖全部供应方项目，可用键 `*` 登记一次。有效的项目特批优先于通用口径。项目特批比例填入对应税率档，审查使用发起当日有效的记录，实际采用的参数与来源随任务保存。
