# ONLYOFFICE 接入

本项目将 DOCX 版本保存于业务数据库，ONLYOFFICE 通过签名 URL 加载文档并回调保存结果。编辑器成功执行操作不等于业务版本已保存；审查和导出均等待保存确认。

## 独立部署依赖

当前 `backend/app/onlyoffice.py` 固定适配构建 `10.0.0-labesign9`，对应 Document Server 10.0.0-169 的定制前端与消息桥接。该编辑器部署位于独立工程，不包含在本仓库中。

宿主通过 `frontend/src/editors/onlyoffice-client.ts` 交换带请求 ID 和文档 key 的消息，核对消息来源与编辑器窗口。正文定位需要编辑器实现相应桥接协议。普通官方镜像不保证具备此桥接，也不能据此声称定位、保存保护等功能已完成接入。

本项目使用普通插件及定制桥接，不依赖 Automation API。自动建议写回、外部批注/修订列表能力默认关闭。

## 环境变量

API 启动前设置：

```sh
export RIXIN_ONLYOFFICE_ENABLED=1
export RIXIN_ONLYOFFICE_PUBLIC_URL=http://127.0.0.1:18083
export RIXIN_ONLYOFFICE_INTERNAL_URL=http://127.0.0.1:18083
export RIXIN_ONLYOFFICE_APP_URL=http://host.docker.internal:8010
export RIXIN_ONLYOFFICE_SECRET_FILE=/absolute/path/to/private-secret-file
```

密钥文件使用纯密钥或单行 `JWT_SECRET=<value>`，需与 Document Server 一致；也可通过 `RIXIN_ONLYOFFICE_SECRET` 注入。密钥只保存在服务端，不写入前端或 Git。

`PUBLIC_URL` 是浏览器访问地址，`INTERNAL_URL` 是 API 请求编辑器命令和文件的地址，`APP_URL` 必须可由 Document Server 容器访问。容器回调宿主 API 时，API 需监听容器可访问的地址；例如本地开发可使用 `--host 0.0.0.0`。更换 API 端口时同步修改 `APP_URL`。

## 编辑和审查行为

当前限制单写会话，已定稿文档使用只读查看。编辑默认启用跟踪更改，修改保留为修订记录。业务版号确认后才显示保存完成。

过程意见的正文定位要求审查版本与当前保存版本一致、正文没有未保存修改，且原文能够唯一匹配。重复文本或原文变化会明确拒绝定位。定位期间再次检查编辑代次，不为定位主动保存正文。

开发验证入口为 `/onlyoffice-integration.html?id=<test-contract-id>`，仅接受 `data_purpose=test` 的合同；测试文件使用 `backend/tests/fixtures/` 中的合成样本。

测试桥接和保存回调可使用 `backend/tests/probes/onlyoffice_collaboration.py`。探针应使用独立数据库，不使用业务合同。停止服务前完成保存；停用编辑器仅关闭能力开关，不删除数据库或回滚文档。
