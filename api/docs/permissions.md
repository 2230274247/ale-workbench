# ALE 实验工作台 · 阶段 3 权限矩阵

版本 1.6.0 · 2026-10-16。OpenAPI 操作的 `x-implementation-status` 是范围依据：`implemented` 为本轮实现合同，`planned` 为保留规划，不表示服务已部署或验收。第四轮新增化学体系、批次批量建样、运行批量绑样与计划归档授权，见文末「第四轮真实授权（1.4.0）」。

## 当前 1.6.0：样品作废与 AI 助手（2026-10-17）

Canonical 与 app.version 均为 1.6.0。103路径、164操作、217 schemas、22 tags；106 implemented / 58 planned。保留既有152操作及operationId，新增样品作废1操作与AI11操作；历史章节的版本与计数只代表当时状态。

- 样品管理调用 `POST /api/v1/samples/{id}/void`，body只有 `expected_row_version`（必填严格正整数）与 `reason`（去首尾空白后1..2000字符）。admin/operator且记录可见；viewer为403。必须是available、只有无实际字段的初始receive、有样品和流转创建审计、没有子样品/科研/来源/其他关联；不满足为409。首次作废只写只读 `voided_at/void_reason/voided_by_user_id` 并递增版本，响应200 Sample。不会改变科学status；详情仍可读取，不能再编辑或新增关联。最新版本+相同原因重试幂等，旧版本或改原因409。`GET /samples` 与 `GET /batches/{id}/samples` 的 `include_voided` 默认false，true包含可见作废记录。
- 所有登录角色可 `GET /api/v1/ai/status`（仅enabled/configured）和 `POST /ai/chat`。chat字段为必填UUID request_id、非空白message（1..4000字符）、可空UUID conversation_id、可空context。context只含kind与id：kind=sample/batch/plan/process/measurement须严格正整数ID（≤9223372036854775807），kind=none须id为null或省略。所有请求拒绝额外字段。
- 仅admin可 `GET/PUT /ai/config`、`GET /ai/models`、`POST /ai/test`、`GET /ai/usage`。test只收必填UUID request_id。config为完整设置替换：revision必填严格非负整数，其余有默认值；模型、端点、provider_options、价格、预算、限额精确边界见AIConfigWrite。仅支持空provider_options或`{"thinking":{"type":"disabled"}}`；但官方api.deepseek.com写入必须为后者（422），旧空配置test/chat在预留前409阻止，GET仍可读取修复；端点须公开HTTPS、443端口且无凭据/查询/fragment；调用时再次校验DNS。输入/输出价格>0、缓存价格≥0且≤输入价格（单价≤10000），月预算>0且≤1000000，均最多8位小数，可传JSON数值或Decimal字符串；响应为Decimal字符串。currency为三个大写字母。月token 1000..10^9、每日调用1..100000、用户/管理员每日1..10000、输出token64..4096、工具轮数1..4，均严格整数。
- 配置操作顺序：先以空model保存端点与密钥，GET models发现，再PUT选择已发现model并启用。修改端点或密钥会清空发现列表。api_key仅写，8..512个ASCII可见非空白字符；地址不变时省略/null保留旧密钥；修改base_url会清除旧密钥，除非同时提供新api_key，clear_api_key=true清除，二者同时指定422。响应只含key_configured/configured、revision、updated_at、discovered_models与pricing_note及公开设置，不返回密钥或密文。revision冲突、降低预算至已记账+预留量以下、活动账期改币种返回409；未发现模型/启用但无密钥422。
- chat请求ID相同且输入相同只结算一次；不同输入409，他人请求ID404。pending响应含status/request_id/conversation_id/answer/sources/tool_trace/usage/error，不含replayed；answer与usage为null，error.code=request_in_progress。首次完成/失败含usage与replayed=false，发现模型成功另含models（对象数组，每项id）。provider/授权变化/工具或大小限制失败仍为HTTP200，必须检查data.status/error；统一包络code仍为0。失败usage可为保守估算。已结算原ID查询不外发、不重复计费；重新核验当前session、配置revision及全部证据，一致则返回原答案/来源/trace并replayed=true，否则status=failed、隐藏答案/来源/trace并给出authorization_changed、configuration_changed或evidence_unavailable。旧版本无证据请求保守隐藏。
- 会话仅本人可复用，admin也不能读/续接他人会话；未知/他人conversation_id返回404，忙会话409。服务端仅参考最近两轮成功请求的用户意图（每轮最多1000字符），最多重新执行四个去重白名单工具计划；使用当前账户范围获取新数据，支持省略ID的追问。客户端不能提交历史，旧模型回答不发送模型。没有会话列表/历史读取API。
- 工具是服务器内部白名单，不是新增HTTP路由：search_records、record_detail、sample_timeline、quality_hints。每次工具调用与交付前重新验证权限和证据；排除作废样品及相关不可见记录。search按化学体系/物种/实际步骤化学信息、批次、显式周期字段、状态、异常与缺失当前测量过滤；分页limit1..20、offset0..99且窗口≤100。详情只投影最少元数据；timeline按追加ID排列并裁剪隐藏关联；quality只计算当前测量的基线/模型/均值缺失、重复组与质量标记，不选择科学前后配对或推断机理。来源仅服务器生成内部链接；trace含tool/status/sources/result_bytes/read_only/origin（旧trace可省略origin），不暴露SQL、文件路径、原始点或任意网络入口。
- usage是admin当前UTC月全用户账本，scope=all_users；含调用次数、输入/输出/cache hit/miss token、charged/reserved token及费用、估算/待处理请求数与预算。金额为字符串；价格由管理员填写，账本不是供应商发票。请求先预留最大量，按max_tool_rounds+1预留chat每日调用槽，test/models为1；调用按派发UTC日记账，跨月未完成请求停止后续外发，旧pending继续保守占未用槽；超过每日或月预算/token限额HTTP429。中断pending在租约内保留预留和忙锁；120秒执行上限、180秒固定租约（旧无租约300秒）后惰性恢复，释放未用预留及忙锁，未知派发费用保守保留，不自动重发。管理员可手动恢复并凭账单对账一次，详见文末。每次外发及最终交付均重新检查session撤销/到期、账户、配置启用/revision和此前全部证据。GET models也调用供应商、保存发现列表并计每日调用；其token/费用预留为0，不能当作无副作用缓存查询。
- HTTP错误使用统一ErrorDetail包络：401认证、403角色、404不可见请求/会话、409配置/版本/幂等/会话/未启用、422验证、429限额、503数据库/迁移不可用、500内部错误。provider内部错误位于HTTP200的data.error，错误文本不会包含供应商原始响应或密钥。

历史验证证据（新增四路由前）：311外部ref全部可解析，OpenAPI3.1通过；真实MySQL902字段映射、32处CHECK枚举一致。AI非数据库投影字段显式x-db-column:false，校验器不会把model/status等映射到无关表；AISourceKind等UI枚举不谎称数据库CHECK。只读事务核对0008/0009实际列/约束/FK及样品metadata一致性，样品2条、作废0条。102业务路由与implemented严格相等；43请求正反例（10接受/33拒绝）与实际backend模型一致，5正/5反结果变体通过，168个生成Python模型JSON schema可构造。生成TS严格tsc通过，frontend声明字节一致。此任务未调用付费供应商、未写科研数据，未替代集成HTTP/浏览器验收。


## 当前角色与权限

| 资源或动作 | admin | operator | viewer |
|---|---|---|---|
| 自己的资料、修改密码、退出 | 允许 | 允许 | 允许 |
| 用户 CRUD、停用、重置密码 | 允许 | 禁止 | 禁止 |
| 邀请创建、分页列表、撤销 | 允许 | 禁止 | 禁止 |
| 批次/样品读取 | 全部 | 自己拥有 | 自己拥有 |
| 批次/样品创建、更新 | 全部 | 自己拥有 | 禁止 |
| 批次/样品删除 | 允许 | 禁止 | 禁止 |
| dashboard summary/recent | 全部范围 | 自己范围 | 自己范围 |
| 计划/计划步骤、运行/实际步骤/样品绑定读取 | 全部 | 自己及关联可见 | 自己及关联可见 |
| 计划/计划步骤、运行/实际步骤/绑定创建、更新、删除 | 全部 | 自己及关联可见 | 禁止 |
| 流转查询 / 追加 | 全部 / 允许 | 自己样品 / 允许 | 自己样品 / 禁止 |

权限标识包括 `auth:self`、`user:manage`、`batch:read/write/delete`、`sample:read/write/delete`。邀请管理仅 admin。`/auth/me.permissions` 描述实际授权；前端隐藏按钮不能替代服务端校验。

## 所有权过滤

`/auth/me.data_scope` 为 `all`（admin）或 `own`（operator/viewer）。普通用户仅访问 `owner_user_id = 当前用户` 的批次与样品；样品所属批次也必须可见。无所有者的历史记录不自动向普通用户开放。没有共享实现，也没有 `shared` 范围。

列表、详情、更新、外键关联检查、分页总数和首页聚合都必须应用同样的所有权约束，不能只隐藏前端页面。创建时由服务端确定所有者，不接受客户端任意指定 owner_user_id。

计划按 owner_user_id、运行按 operator_user_id 过滤；计划关联批次必须可见，运行关联批次、计划及所有参与样品均必须可见。无所有者/操作者记录仅 admin 可见。Phase 2 写入和删除使用 writer（admin/operator），越权资源返回 404；viewer 写入返回 403。批次/样品删除仍仅 admin。任何科学依赖会阻止删除（409），不会级联或置空关联。

计划/运行 PATCH 的 expected_row_version 可选；子项 PATCH/DELETE 比较父计划/运行版本，成功递增父 row_version。追加流转必须提供样品 expected_row_version。绑定不会改状态；load/unload 负责占用，step_id 表示实际步骤完成之后，历史按 transition_id 追加序。

## 认证与管理

注册始终需要有效、未使用、未撤销且未过期的邀请码；注册角色来自邀请。邀请仅可授予 viewer/operator，默认 viewer；管理员可直接创建用户（默认 viewer）。setup_code 只用于初始化首位管理员。

Argon2id 存密码哈希。access JWT 为 1 小时，refresh JWT 为 7 天，并绑定数据库可撤销会话。刷新时轮换 refresh，旧令牌失效。登出撤销当前会话并清除 cookie；停用、本人改密、管理员重置密码撤销目标用户全部会话。刷新请求可省略 body 或发送 `{}`，缺省 refresh_token 时回退到 HttpOnly、SameSite=Strict cookie，HTTPS 下使用 Secure。

## 保留规划

审计日志查询、样品证据、手工测量创建/删除与点写入、分析、科研台账、source POST/PATCH/verify、dataset 写入及独立 channels/datapoints 路由、图表导出、设备写入/详情、配方与光学模型、dashboard upcoming-plans/alerts 为 planned。测量 GET/质量 PATCH/supersede、source GET/下载、dataset GET 与导入4操作已实现。批次下样品查询、流转、计划和执行已实现。已实现受限 multipart 多文件预览/确认；无共享。规划接口与模型存在不表示已获得可调用能力。


### 2026-10-15 第二轮收尾规则

运行有任意流转历史后，禁止对运行本体、该运行全部实际步骤及全部样品绑定进行任何 PATCH（含空 PATCH、实际参数、备注、附加字段），返回409；刷新版本不能解除历史保护。无历史运行仍可按权限和版本约束编辑。

样品可见但关联运行不可见时，历史响应必含 context_redacted=true，并将 process_id、step_id、operator_user_id、location、note、measurement_id 六字段置NULL，状态轨迹和追加顺序保留。页面显示“关联信息受权限保护”，不显示为“无关联执行”或“未填写备注”；未裁剪行为 context_redacted=false。


## 第三轮真实授权（1.3.0）

| 动作 | admin | operator | viewer |
|---|---|---|---|
| import jobs 列表/详情 | 仅本人 | 仅本人 | 仅本人 |
| preview / confirm | 本人 | 本人 | 禁止 |
| measurement GET/points | 全部 | 可见样品 | 可见样品 |
| quality PATCH / supersede | 全部 | 可见样品 | 禁止 |
| source GET/content | 全部 | occurrence/样品/测量/点/旧dataset授权 | 同operator |
| dataset GET | 全部 | 可见样品或本人operator_user_id | 同operator |

suggestions 样品候选始终仅上传者本人（含admin）。source详情的occurrences独立过滤，源文件全局名字/路径/备注不透出。supersede要求双方版本且同样品；质量PATCH仅quality_flag/quality_note。不存在的写路由不会因用户为admin而变成implemented。`writer`/`current_user`及行范围判断是实际授权依据；permissions字符串不代替校验。


## 第四轮真实授权（1.4.0）

| 动作 | admin | operator | viewer |
|---|---|---|---|
| chemistry-systems / species / templates 读取 | 全部 | 仅自己拥有（`owner_user_id` = 本人） | 同 operator |
| 上述创建、更新（species/template 通过父体系归属判定） | 允许 | 自己拥有 | 禁止 |
| 上述删除 | 允许 | 禁止 | 禁止 |
| 未归属体系（`owner_user_id IS NULL`，例如归属人被删除） | 允许 | 不可见（404） | 不可见（404） |
| 不可见或他人归属的体系/物种/模板 | 404（不透露归属，不区分"不存在"与"无权"） | 404 | 404 |
| 批次内批量建样 `POST /batches/{id}/samples/batch` | 全部可见批次 | 自己拥有批次 | 禁止 |
| 运行批量绑样 `POST /processes/{id}/samples/batch` | 全部 | 自己及关联可见运行 | 禁止 |
| 计划归档 `POST /plans/{id}/archive` | 允许 | 自己拥有计划 | 禁止 |
| 计划删除 `DELETE /plans/{id}` | 允许 | 自己拥有计划 | 禁止 |

化学体系的 `system_id` 是 API/契约的主键名；`processes.chemistry_system_id` 为可空外键，`ON DELETE SET NULL`，删除体系不会删除执行记录，只把关联置空。删除体系在被任何执行引用时返回 409（`Scientific dependencies prevent deletion`），删除物种/模板同样仅 admin。执行层关联化学体系属于 `PATCH/POST /processes`，写入者需为 `writer` 且对运行可见；步骤请求体（`ProcessStepCreate/Update`）**不接受** `chemistry_system_id`，携带即 422。批量建样与批量绑样都在单一事务内完成，任一条失败整体回滚（重复编码/重复绑定 409，越界数量或母片不符 422），父批次/运行的版本只自增一次。计划归档只改 `status`，幂等；已被执行引用的计划删除返回 409，归档不受影响。前端隐藏按钮不代表授权，`writer`/`current_user`/`admin` 及行范围判断才是实际依据。


## 历史：第五轮实际能力（1.5.0）

- `DELETE /imports/{job_id}`：writer 且仅任务本人（含 admin），可选 query `expected_row_version`。成功 HTTP 200，data 为 `{job_id, deleted:true, cleanup:string}`。已生成正式测量、已归档原件或任何来源引用返回409；事务完成后仅清理全局无引用暂存原件。
- `GET /imports/options/samples`：可见样品分页，page默认1、size默认50（1..200）、keyword≤128，搜索样品编码/显示名/批次编码；返回 sample_id/sample_code/display_label/batch_code。`GET /imports/options/samples/{sample_id}` 返回 sample、已绑定且可见的 processes（id/code）与当前可见 baseline_measurements（id/code/stage/stage_seq/optical_model_id）。这些选项不能替代确认时权限及关联校验。
- `GET/POST /step-parameter-templates` 与 `GET/PATCH/DELETE /step-parameter-templates/{id}`：admin全范围，operator/viewer只读本人模板；writer创建/更新/删除可见模板。分页size默认20（1..200），keyword≤128。创建返回201，PATCH返回200，DELETE返回204；更新body与删除query均必填 expected_row_version，冲突409。PATCH版本必须严格整数，可只提交版本；template_name/definition省略保持原值，显式null为422。
- `ParameterSnapshot`精确复用`backend/app/step_templates.py`：`step_type`必填（1..128）；`temperature`默认`{value:null,unit:"°C"}`，unit非空≤32；`groups`默认空数组、最多32组。每组`name`必填（1..128），fields默认空数组、最多64项；每项name必填、value可空字符串≤2000、unit可空字符串≤32。组名及同组字段名不能重复；所有层级拒绝额外字段并去首尾空白，数值输入不自动转字符串。计划/实际步骤Create/Update/响应均含可空`parameter_snapshot` JSON，模板修改不回写已保存快照。原TemplateCreate/Update仍指化学体系模板；新增独立请求类型为StepParameterTemplateCreate/Update。
- `POST /batches/{id}/archive`与`POST /processes/{id}/archive`使用`RecordArchive`（严格正整数expected_row_version必填）；writer且记录可见。分别返回Batch/ProcessDetail，首次设置可空archived_at并递增版本，携带最新版本重复操作幂等；原科学status、依赖与历史保留。计划archive沿用原PlanArchive及status语义。
- 原`listTools`保持operationId，`GET /tools`已实现，所有登录角色可读取共享设备列表。page默认1、size默认20（1..200），keyword≤128匹配tool_code/tool_name；原规划tool_type/status过滤不再宣称支持，其他设备写入/详情仍planned。


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
