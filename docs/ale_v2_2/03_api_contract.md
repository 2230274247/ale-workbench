# V2.2 API 契约

复用 `/api/v1`、既有Bearer会话、统一envelope/request_id、writer/current_user及不可见404规则。公开实时契约 `/openapi.json`；本次快录路径在 `/api/v1/quick`，属于兼容扩展，不冒称已将所有新路径写入历史手工canonical YAML。

| 能力 | 方法 / 路径 |
|---|---|
| 材料查询/幂等新增 | GET/POST /quick/materials |
| 日期序号建议 | GET /quick/next-number?experiment_date=YYYY-MM-DD |
| 分页历史/完整筛选 | GET /quick/runs |
| 保存草稿/正式记录 | POST /quick/runs（201，幂等idempotency_key） |
| 回读/版本更新 | GET/PUT /quick/runs/{process_id} |
| 修订历史 | GET /quick/runs/{process_id}/revisions |
| 参数模板 | GET/POST /quick/templates |
| 量测原件解析预览 | POST multipart /quick/runs/{id}/preview |
| 逐块确认补录 | POST /quick/imports/{token}/confirm |
| 原件校验下载 | GET /quick/imports/{token}/original |
| 导出预览/就绪度 | GET /quick/dataset/preview、/readiness |
| 文件流导出 | GET /quick/dataset/download?format=xlsx/json/wide/readiness_json/readiness_html |

复制与继续由前端读取已有快照、清空结果/重建UUID后POST标准新建实现；服务器只根据已授权previous_run_id继承sequence_id。结果编辑使用整个运行的原子PUT，避免参数和结果分开半写。模板只从已保存且属于当前账户的运行生成（管理员可读他人记录但不能给其附加私人模板/原件）。

筛选：material_id、date_from/to、equipment、data_nature、quality_status、has_epc、has_uniformity、excel；分页50次运行，结果条数单独统计；文件导出使用完整筛选集合。导出记录存清单、版本、过滤条件和输出SHA256，无公开原件路径。

400/422非法字段、401会话、403只读写入、404不可见、409当天序号/幂等/版本/覆盖冲突、503存储不可用。重要错误含中文恢复建议与VERSION_CONFLICT/IMPORT_CONFLICT/IMPORT_UNSUPPORTED_FORMAT语义；沿用旧统一数值错误码，未修改全站错误协议。所有body禁止额外字段与非有限数值。原始凭据、SQL参数不进入错误消息。
