# API contract changes（原位延续）

当前版本 **1.6.0，2026-10-17**。99路径160操作、207 schemas、22 tags；102 implemented / 58 planned。仅修改api目录及frontend/src/contracts.d.ts。

## 当前 1.6.0：样品作废与 AI 助手（2026-10-17）

Canonical 与 app.version 均为 1.6.0。99路径、160操作、207 schemas、22 tags；102 implemented / 58 planned。保留既有152操作及operationId，新增样品作废1操作与AI7操作；历史章节的版本与计数只代表当时状态。

- 样品管理调用 `POST /api/v1/samples/{id}/void`，body只有 `expected_row_version`（必填严格正整数）与 `reason`（去首尾空白后1..2000字符）。admin/operator且记录可见；viewer为403。必须是available、只有无实际字段的初始receive、有样品和流转创建审计、没有子样品/科研/来源/其他关联；不满足为409。首次作废只写只读 `voided_at/void_reason/voided_by_user_id` 并递增版本，响应200 Sample。不会改变科学status；详情仍可读取，不能再编辑或新增关联。最新版本+相同原因重试幂等，旧版本或改原因409。`GET /samples` 与 `GET /batches/{id}/samples` 的 `include_voided` 默认false，true包含可见作废记录。
- 所有登录角色可 `GET /api/v1/ai/status`（仅enabled/configured）和 `POST /ai/chat`。chat字段为必填UUID request_id、非空白message（1..4000字符）、可空UUID conversation_id、可空context。context只含kind与id：kind=sample/batch/plan/process/measurement须严格正整数ID（≤9223372036854775807），kind=none须id为null或省略。所有请求拒绝额外字段。
- 仅admin可 `GET/PUT /ai/config`、`GET /ai/models`、`POST /ai/test`、`GET /ai/usage`。test只收必填UUID request_id。config为完整设置替换：revision必填严格非负整数，其余有默认值；模型、端点、provider_options、价格、预算、限额精确边界见AIConfigWrite。仅支持空provider_options或`{"thinking":{"type":"disabled"}}`；但官方api.deepseek.com写入必须为后者（422），旧空配置test/chat在预留前409阻止，GET仍可读取修复；端点须公开HTTPS、443端口且无凭据/查询/fragment；调用时再次校验DNS。输入/输出价格>0、缓存价格≥0且≤输入价格（单价≤10000），月预算>0且≤1000000，均最多8位小数，可传JSON数值或Decimal字符串；响应为Decimal字符串。currency为三个大写字母。月token 1000..10^9、每日调用1..100000、用户/管理员每日1..10000、输出token64..4096、工具轮数1..4，均严格整数。
- 配置操作顺序：先以空model保存端点与密钥，GET models发现，再PUT选择已发现model并启用。修改端点或密钥会清空发现列表。api_key仅写，8..512个ASCII可见非空白字符；地址不变时省略/null保留旧密钥；修改base_url会清除旧密钥，除非同时提供新api_key，clear_api_key=true清除，二者同时指定422。响应只含key_configured/configured、revision、updated_at、discovered_models与pricing_note及公开设置，不返回密钥或密文。revision冲突、降低预算至已记账+预留量以下、活动账期改币种返回409；未发现模型/启用但无密钥422。
- chat请求ID相同且输入相同只结算一次；不同输入409，他人请求ID404。pending响应含status/request_id/conversation_id/answer/sources/tool_trace/usage/error，不含replayed；answer与usage为null，error.code=request_in_progress。首次完成/失败含usage与replayed=false，发现模型成功另含models（对象数组，每项id）。provider/授权变化/工具或大小限制失败仍为HTTP200，必须检查data.status/error；统一包络code仍为0。失败usage可为保守估算。已结算原ID查询不外发、不重复计费；重新核验当前session、配置revision及全部证据，一致则返回原答案/来源/trace并replayed=true，否则status=failed、隐藏答案/来源/trace并给出authorization_changed、configuration_changed或evidence_unavailable。旧版本无证据请求保守隐藏。
- 会话仅本人可复用，admin也不能读/续接他人会话；未知/他人conversation_id返回404，忙会话409。服务端仅参考最近两轮成功请求的用户意图（每轮最多1000字符），最多重新执行四个去重白名单工具计划；使用当前账户范围获取新数据，支持省略ID的追问。客户端不能提交历史，旧模型回答不发送模型。没有会话列表/历史读取API。
- 工具是服务器内部白名单，不是新增HTTP路由：search_records、record_detail、sample_timeline、quality_hints。每次工具调用与交付前重新验证权限和证据；排除作废样品及相关不可见记录。search按化学体系/物种/实际步骤化学信息、批次、显式周期字段、状态、异常与缺失当前测量过滤；分页limit1..20、offset0..99且窗口≤100。详情只投影最少元数据；timeline按追加ID排列并裁剪隐藏关联；quality只计算当前测量的基线/模型/均值缺失、重复组与质量标记，不选择科学前后配对或推断机理。来源仅服务器生成内部链接；trace含tool/status/sources/result_bytes/read_only，不暴露SQL、文件路径、原始点或任意网络入口。
- usage是admin当前UTC月全用户账本，scope=all_users；含调用次数、输入/输出/cache hit/miss token、charged/reserved token及费用、估算/待处理请求数与预算。金额为字符串；价格由管理员填写，账本不是供应商发票。请求先预留最大量，按max_tool_rounds+1预留chat每日调用槽，test/models为1；调用按派发UTC日记账，跨月未完成请求停止后续外发，旧pending继续保守占未用槽；超过每日或月预算/token限额HTTP429。中断pending保留预留和会话忙锁，不自动退款或重试；目前无自动崩溃恢复，不能用新ID绕过同会话忙锁。每次外发及最终交付均重新检查session撤销/到期、账户、配置启用/revision和此前全部证据。GET models也调用供应商、保存发现列表并计每日调用；其token/费用预留为0，不能当作无副作用缓存查询。
- HTTP错误使用统一ErrorDetail包络：401认证、403角色、404不可见请求/会话、409配置/版本/幂等/会话/未启用、422验证、429限额、503数据库/迁移不可用、500内部错误。provider内部错误位于HTTP200的data.error，错误文本不会包含供应商原始响应或密钥。

验证证据：311外部ref全部可解析，OpenAPI3.1通过；真实MySQL902字段映射、32处CHECK枚举一致。AI非数据库投影字段显式x-db-column:false，校验器不会把model/status等映射到无关表；AISourceKind等UI枚举不谎称数据库CHECK。只读事务核对0008/0009实际列/约束/FK及样品metadata一致性，样品2条、作废0条。102业务路由与implemented严格相等；43请求正反例（10接受/33拒绝）与实际backend模型一致，5正/5反结果变体通过，168个生成Python模型JSON schema可构造。生成TS严格tsc通过，frontend声明字节一致。此任务未调用付费供应商、未写科研数据，未替代集成HTTP/浏览器验收。


## 历史：第五轮实际能力（1.5.0）

- `DELETE /imports/{job_id}`：writer 且仅任务本人（含 admin），可选 query `expected_row_version`。成功 HTTP 200，data 为 `{job_id, deleted:true, cleanup:string}`。已生成正式测量、已归档原件或任何来源引用返回409；事务完成后仅清理全局无引用暂存原件。
- `GET /imports/options/samples`：可见样品分页，page默认1、size默认50（1..200）、keyword≤128，搜索样品编码/显示名/批次编码；返回 sample_id/sample_code/display_label/batch_code。`GET /imports/options/samples/{sample_id}` 返回 sample、已绑定且可见的 processes（id/code）与当前可见 baseline_measurements（id/code/stage/stage_seq/optical_model_id）。这些选项不能替代确认时权限及关联校验。
- `GET/POST /step-parameter-templates` 与 `GET/PATCH/DELETE /step-parameter-templates/{id}`：admin全范围，operator/viewer只读本人模板；writer创建/更新/删除可见模板。分页size默认20（1..200），keyword≤128。创建返回201，PATCH返回200，DELETE返回204；更新body与删除query均必填 expected_row_version，冲突409。PATCH版本必须严格整数，可只提交版本；template_name/definition省略保持原值，显式null为422。
- `ParameterSnapshot`精确复用`backend/app/step_templates.py`：`step_type`必填（1..128）；`temperature`默认`{value:null,unit:"°C"}`，unit非空≤32；`groups`默认空数组、最多32组。每组`name`必填（1..128），fields默认空数组、最多64项；每项name必填、value可空字符串≤2000、unit可空字符串≤32。组名及同组字段名不能重复；所有层级拒绝额外字段并去首尾空白，数值输入不自动转字符串。计划/实际步骤Create/Update/响应均含可空`parameter_snapshot` JSON，模板修改不回写已保存快照。原TemplateCreate/Update仍指化学体系模板；新增独立请求类型为StepParameterTemplateCreate/Update。
- `POST /batches/{id}/archive`与`POST /processes/{id}/archive`使用`RecordArchive`（严格正整数expected_row_version必填）；writer且记录可见。分别返回Batch/ProcessDetail，首次设置可空archived_at并递增版本，携带最新版本重复操作幂等；原科学status、依赖与历史保留。计划archive沿用原PlanArchive及status语义。
- 原`listTools`保持operationId，`GET /tools`已实现，所有登录角色可读取共享设备列表。page默认1、size默认20（1..200），keyword≤128匹配tool_code/tool_name；原规划tool_type/status过滤不再宣称支持，其他设备写入/详情仍planned。

验证：`validate_contract.py --no-db`与带真实MySQL校验均通过；284外部ref、894字段映射、31处CHECK枚举一致。生成152个Python模型JSON schema可构造；快照7组正反例与backend接受/拒绝及默认值结果一致；模板/归档严格版本与null语义一致，四个步骤请求字段集合一致。生成TS严格tsc通过，frontend contracts与生成TS字节一致。仅契约工具读取information_schema；本任务未写backend、迁移或frontend应用代码。

历史1.5.0集成记录：当时94个注册业务操作与implemented集合完全相等；当时app.version滞后。当前app.version已为1.6.0，以上当前章节为准。

## 1.4.0 第四轮 contract changes（2026-10-16）

- 保留旧128操作及operationId，新增化学体系11操作、批次批量建样1操作、运行批量绑样1操作、计划归档1操作；86路径142操作、174 schemas、20 tags，83 implemented / 59 planned。新增的14个操作全部对应 backend 已注册路由（`app/chemistry.py`、`records.py`、`experiments.py`）。
- 化学体系：`ChemistrySystem.system_id` 为 API/契约主键名；只有 `Process`/`ProcessCreate`/`ProcessUpdate` 携带可空 `chemistry_system_id`，`ProcessStep*` 不携带（`extra='forbid'`，携带即 422）。物种与模板通过父体系创建，更新/删除走独立子资源路径。
- 批量接口：`BatchSampleCreate.items`(1..50) 与 `BatchLinkCreate.sample_ids`(1..50) 单事务全成或全不成，父版本只自增一次；重复 409、越界或归属不符 422。
- 计划与步骤：`PlanStatus` 加入 `archived`；`PlanArchive` 只含 `expected_row_version`；`experiment_plan_steps`/`process_steps` 新增可选 `step_name`(≤128) 与 `custom_parameters`(JSON 行数组：名称/值/单位)；`process_steps` 新增可选 `plan_step_id` 映射。旧 O₃/HF/TMA 字段保留且不再必填。
- 同步范围：`openapi/openapi.yaml`、`openapi.bundled.yaml`、`components/schemas/*`、`paths/chemistry.yaml` 等路径文件、`api/models/typescript/api.d.ts`、`api/models/python/schemas.py`、`frontend/src/contracts.d.ts` 一并更新；生成模型可导入且 TS 严格检查通过。校验器仍只读 information_schema，不执行迁移或写入。

- 保留旧123操作及operationId，新增imports列表/preview/详情/confirm与source content共5操作；77路径128操作，155 schemas，19 tags，69 implemented / 59 planned。69个已实现操作全部对应backend已注册路由，后端业务路由没有遗漏；health与文档/SPA路由不计入业务契约。
- multipart files[]、14字段ImportChoice、原子confirm与重放、复杂parser JSON/warnings/suggestions，quality-only PATCH及双方版本supersede均同步。source GET使用安全投影与可见occurrences，下载为binary；dataset只实现列表/详情可选嵌套通道/点。
- source verify/POST/PATCH、手工measurement POST、点写入、dataset写入、独立通道/数据点路由等继续planned。
- 修复生成器对files[]属性、nullable分支数值/长度边界、请求strict/空白reason/重复item_id/至少一个质量字段的处理。Python生成模型可导入，所有模型JSON schema可构造；生成TS与frontend contracts字节一致。
- 验证：validate_contract.py（带数据库）通过，237外部ref可解析、835字段映射通过、31处CHECK枚举一致；仅SELECT information_schema，没有数据库写入。gen_models.py、gen_swagger_preview.py通过。真实backend Choice/Confirmation/QualityUpdate/Supersede与生成模型字段、必填、数值/长度/默认值逐项对齐；5项负向语义用例通过；纯parser unsupported/XML/Eoptics结果通过生成模型校验；TS严格检查通过。对应证据已在本轮命令输出中保留。

---

## 历史：Phase 1 API contract changes

版本：1.1.0，2026-10-15。仅修改 H:\ALE_AI\api；未修改 backend/frontend/database/reports。

- Canonical source：openapi/openapi.yaml + paths/*.yaml + components/schemas/*.yaml。保留原有 114 操作，新增 setup-status/setup 与邀请管理 5 操作，共 70 路径、119 操作、118 schemas。29 操作标记 implemented（本轮实现合同，不代替运行验收），90 标记 planned。
- 阶段 1：认证 8、用户管理 6、邀请管理 3、批次/样品 CRUD 各 5、dashboard summary/recent 2。批次下样品子路由、样品证据、审计查询及其他科研接口仍为 planned；无批量导入、共享、后续科研写入实现。
- OpenAPI 3.1 全局去除 nullable，改用 type 联合或 anyOf/ref/null。类型生成保留 nullable DECIMAL，TS readonly，Python allOf 引用及内联扩展字段，全部模型定义后 model_rebuild；分页统一 data[] 与同级 meta。
- 注册 invite_code 必填，角色来自一次性邀请；邀请 role 为 viewer/operator，默认 viewer，expires_in_hours 为 1..168 整数、默认 72。Invitation 安全视图不含代码/哈希，创建返回平铺字段与仅一次 invite_code。CreateUserRequest = 注册字段减 invite_code 加默认 viewer 的 role；UserUpdate 全部部分更新且无 ID。
- GET setup-status 返回 data.needs_setup；POST setup 接收 setup_code/username/password/display_name?，201 返回 User。refresh body 可省略或为 {}，显式 token 优先，否则读取 cookie。
- User/CurrentUser 描述及权限文档：admin 全部；operator/viewer 只限自己 owner_user_id 的批次与样品，样品所属批次也须可见；无共享。Argon2id、access JWT 1 小时、refresh JWT 7 天、数据库会话撤销与刷新轮换、HttpOnly/SameSite=Strict cookie（HTTPS Secure）。
- Batch/Sample 响应新增只读 row_version；更新新增可选 expected_row_version，冲突 409。既有科研数据形状保留。
- validate_contract.py 数据库连接/核对异常、枚举缺失或双向不匹配均失败退出；--no-db 显式说明未核对数据库。打包保留 $ref sibling（如 role 默认值）。Swagger 两份预览标明 implemented/planned 范围，内嵌契约的 UI 资源仍需联网。

验证：--no-db OpenAPI 3.1 校验通过；TS tsc --noEmit --strict 通过；Python 生成模型导入、全部 JSON schemas、前向引用、allOf 字段、nullable ref/Decimal、邀请码必填、邀请范围、默认角色及分页行为通过；注入枚举不匹配确认返回 1。已运行生成器生成 bundle、TS/Python 模型及两份 Swagger。

数据库全量校验：字段核对通过；现有 issues_links.entity_type 仍为 7 值，缺 derived_result/instrument_dataset，枚举校验正确返回 1。保留契约规划的 9 值，待主任务数据库迁移完成后重新运行；未据此宣布全量校验通过。

跨目录联调差异（只读检查时的状态，待各负责人同步）：

- backend/app/auth.py：setup-status 仍返回 setup_required；setup/register 仍返回 {token,user}，契约要求 needs_setup 与 User；refresh 参数仍必需 body，契约允许省略。
- backend/app/users.py：创建邀请仍返回 {invitation,invite_code}，契约要求平铺 Invitation + invite_code；frontend/src/views/UsersView.vue 类型仍声明嵌套 invitation（实际只读取 invite_code）。
- backend/app/dashboard.py：recent 仍返回审计活动数组，契约保留 DashboardRecentActivity 对象（recent_samples/recent_processes/recent_measurements）；summary 契约已有当前测量 is_current 语义，后端应据此过滤。
- backend/app/schemas.py：邀请码长度最大 128，与既有契约 64 不同；版本号允许 0，契约最小 1。UserCreate 额外支持 status/notes，契约按任务要求采用 Register 减邀请码加 role。

后续命令（在 api/tools 目录）：python validate_contract.py；python gen_models.py；python gen_swagger_preview.py。数据库未迁移时可用 validate_contract.py --no-db 单独验证/打包，但不得当作数据库一致性通过。

### 2026-10-17 AI Chat Completions 官方协议更正

2026-10-17 官方协议修复：初始当前记录及追问预查均为 `role=user` 的 `<UNTRUSTED_DATABASE_EXCERPT>` JSON 数据消息，含 `current_context`／`prior_plan_reexecuted` 来源及工具名/参数；角括号转义后JSON解码仍保真，数据库文本不能伪造外层分隔符。仅服务器system指令具有权威性；数据内指令、角色文字及旧用户意图不是指令或独立证据。首批消息无伪造assistant/tool；只有本轮服务商实际返回并校验的assistant.tool_calls才回填tool_call_id结果。预查继续执行当前scope查询、来源追踪和证据hash，外发/交付/重放继续重验；旧模型答案不外发。无成功当前查询时仍要求工具，模型直接答复以lookup_required隐藏，拒绝工具结果不能充当成功证据。

官方主机 `api.deepseek.com`（含/v1、/beta路径及主机大小写）必须显式 `provider_options={"thinking":{"type":"disabled"}}`，按主机匹配，不按服务商名称或模型ID猜测。配置PUT缺失时422；既有空配置GET仍可读取，test/chat在预算预留和网络前409阻止，底层completion另有防线；models发现可继续。前端输入该地址或读取旧配置后自动勾选并锁定“显式关闭 thinking”，显示官方默认thinking开启及本助手非思考工具流程的说明；需点击保存，才写入服务端。其他服务商保持其原配置，可自行取消参数。仍采用无成功预查时tool_choice=required、有证据后auto；显式关闭thinking解决官方required限制，未改用其他API或硬编码模型。


### 2026-10-17 正式接入契约收尾（1.6.0）

保持1.6.0；103路径、164操作、217 schemas、22 tags，106 implemented / 58 planned。原160操作的operationId与实施状态全部保留，新增四个AI操作；未修改或执行任何已应用SQL。

| 方法与路径（前缀 /api/v1） | 身份与结果 |
|---|---|
| GET /ai/requests | 所有登录角色，普通用户仅本人，admin全用户；返回AIRequestList（requests最新100条、limit=100，按created_at/request_id倒序），无分页或查询参数 |
| GET /ai/requests/{request_id} | UUID；本人或admin，未知/他人404；返回AIRequestAccountOwner或AIRequestAccountAdmin |
| POST /ai/recover | 仅admin，无body；返回recovered_request_ids与recovered_count；只处理已过期pending |
| POST /ai/requests/{request_id}/reconcile | 仅admin，body=AIReconcileRequest；返回AIRequestAccountAdmin；仅终态且usage_estimated=true可对账一次 |

列表/详情仅账目：request_id、conversation_id、purpose(chat/test/models)、status、created_at、finished_at、lease_expires_at、heartbeat_at、dispatched_calls、charged_tokens、charged_cost、usage_estimated、recovery、reconciled。普通用户无owner、账期、预留或审计详情；admin另含owner_user_id、period、reserved_tokens、reserved_cost、reconciliation_history。reserved_*是请求原始预留快照，终态仍保留原值；活动预留以GET /ai/usage为准。请求/完成时间经统一包络转UTC带时区；lease/heartbeat/recovery.at及审计at为元数据UTC无时区ISO原字符串。无prompt、answer、原执行token、SQL或内部证据泄漏。

每轮执行硬上限120秒，单HTTP调用25秒；新请求固定180秒租约，不因heartbeat无限续期；旧无lease元数据请求宽限300秒。读取账目、usage、配置等入口及新请求会惰性恢复，也可admin手动recover；无独立后台计时器。过期后CAS只结算一次并清空busy_request_id、隔离旧执行token，迟到执行不能二次扣费或改写终态。未派发额度释放，已测量调用按真实usage保留；已派发但结果未知按每调用预留保守收费（usage.estimated=true）。不自动退款未知费用、不自动重发。恢复结果HTTP200 data.status=failed、error.code=request_recovered，另含recovery={recovered:true,unknown_calls,reconciliation_required}；账目recovery则为{at,unknown_calls}或null，两个结构不能混用。

对账字段：reconciliation_id为必填UUID；reason 10..1000字符、evidence 10..2000字符，去空白后均至少10字符（不自动trim）；actual_prompt_tokens及actual_completion_tokens必填，actual_cache_hit_tokens默认0，均严格整数0..1000000000，拒绝bool/字符串/小数；cache_hit不能大于prompt。actual_cost必填，有限非负Decimal，最大1000000且最多8位小数，接受JSON数值或十进制字符串。拒绝额外字段。带相同ID及完全相同submission重试幂等；同ID不同内容、第二个ID、pending或非估算请求409。实际费用可为0、部分或高于估算，允许真实账单超预算并调整原账期；charged_tokens=prompt+completion、cache_miss=prompt-cache_hit，usage_estimated改false，恢复结果reconciliation_required改false，状态仍failed。保留原usage、原result.usage、完整submission、actor_user_id、at审计；不调用供应商。

新trace含origin=current_context/prior_plan/model，分别为当前记录预查、先前计划按当前权限重执行、本轮模型实际工具调用；为兼容旧持久化trace该字段可省略，未知值拒绝。provider的401/402/403/400或422/429依次映射provider_auth_failed/provider_insufficient_balance/provider_permission_denied/provider_parameter_invalid/provider_rate_limited；明确拒绝不估算收费，不重试；5xx为provider_unavailable并保守未知。finish_reason=length为provider_output_truncated，content_filter为provider_content_filtered，aborted/insufficient_system_resource为provider_generation_interrupted；隐藏不完整答案，保留已测usage。以上均在本服务HTTP200 data.error，勿误当本服务HTTP状态；错误信息不拼接上游body。

本次本地验证：OpenAPI3.1及AST路由一致性通过；177个生成Python模型JSON schema可构造；请求17正例/62反例与实际backend模型的接受、默认值、规范化完全一致；5正/5反基础结果及新增恢复、账目、审计、trace origin、安全错误正反例通过。生成TS严格tsc通过，frontend/src/contracts.d.ts与生成文件字节相等。未宣称Windows启动、真实密钥/付费供应商或浏览器正式接入验收；数据库检查范围以现有validation/parity日志最后一段为准。
