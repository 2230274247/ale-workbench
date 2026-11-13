# ALE 工作台开发进度


## 2026-11-13 批量导入：日期自动规范化 + 新材料审核入库 + 记录表每页条数
用户反馈两份需求：①批量导入上传的原表里日期写成 `2026.8.24`、材料 `ZnO`/`HfO2` 不在材料目录，预览整行报错，希望后端自动优化日期格式、把缺失材料自动添加并最后审核；②「记录与结果」表太长，希望加每页条数下拉（10/20/50/100，默认 10）。

**修改文件**：
- `backend/app/quick_batch.py`：`_date()` 改为自动规范化日期——接受 `datetime/date`、`YYYY-MM-DD`（含带时间）、`YYYY.M.D`、`YYYY/M/D`、`YYYY-M-D`、`YYYY年M月D日`，无法解析才报错；`build_row()` 签名加 `new_materials`，材料不在目录时不再报错，而是预生成 `material_id` 并给该行打 `_material_name` 标记；`preview` 返回 `new_materials`（去重、按出现顺序）供审核；`confirm` 在同一请求事务内先幂等插入新材料（`quick_materials`，精确按名称匹配、不推断化学身份），再建 Run，响应新增 `created_materials`。预览仍不写库，SHA-256 指纹覆盖新增字段。
- `backend/app/quick.py`：`GET /quick/runs` 增加 `size:int=Query(10,ge=1,le=100)`，默认每页 10 条。
- `frontend/src/views/QuickDatasetView.vue`：记录表分页条加「每页 10/20/50/100」下拉（默认 10），分页数学改用 `totalPages`；批量导入文案更新；预览新增「将自动新增材料：…」提示，材料列显示 `_material_name`；确认入库提示新增材料名。
- `frontend/src/mobile/MobileDatasetView.vue`：移动端预览同样显示将新增材料、材料列显示 `_material_name`、确认提示新增材料名。
- `frontend/src/views/QuickRecordView.vue`：「继续/历史」选择器显式 `size=100`，避免因默认改 10 而只看到最近 10 条。
- `frontend/src/quick/quick.css`：新增 `.quick-page-size` 行内下拉样式。
- `backend/tests/test_quick_v22.py`：新增 `test_stage3_batch_import_normalizes_dates_and_auto_creates_materials`（点分日期 `2026.8.24` + 新材料 `ZnO` → 预览无错、`new_materials=['ZnO']`、日期归一 `2026-08-24`，确认后 `created_materials=['ZnO']` 且材料目录可查到、Run 回读 `material_name='ZnO'`）。
- `docs/ale_v2_2/04_excel_mapping_contract.md`：批量导入合同同步「日期自动规范化、材料不在目录先列 `new_materials` 审核、确认入库自动创建」。

**验证**：
- 纯函数离线核对（当前工作树无 venv/MySQL，不能跑 pytest）：`_date` 对 `2026.8.24/2026.1.22/2026-8-24/2026/8/24/2026年8月24日/2026-03-06 00:00:00/datetime/date` 均正确归一为 `YYYY-MM-DD`，`2026.13.1`、`abc` 正确报错；`build_row` 对缺失材料生成稳定 `material_id` 且 `_material_name` 标记正确、同材料多行复用同一 id。
- `python -c ast.parse` 对 `quick_batch.py`、`quick.py`、`test_quick_v22.py` 通过。

**边界 / 未验证**：新增 pytest 用例与前端 `vue-tsc`/`npm run build` 因本工作树缺少依赖与 `*_test` 数据库未实际执行；真实浏览器与正式账户验收待用户本人双击「启动工作台.cmd」+ `Ctrl+F5` 强刷确认。材料精确按名称匹配，大小写/别名差异不会被自动合并（不推断化学身份）。


## 2026-11-11 阶段 10 仓库整理与 GitHub 托管
- 新建 `.gitignore` 独立规则：排除 `.env / .appcreds / .dbcreds / .setup-code / .ai-master-key`、`mysql_data/`、`mysql-server/`、`storage*/`、`backups/`、`reports/`、`logs*/`、`node_modules/`、`frontend/dist/`、虚拟环境、`.claude/`、`.workbuddy/`；首次提交 278 文件 / 120502 行，暂存扫描无明文密钥。
- 新增 `README.md`（功能、技术栈、目录、七步上手、配置表、测试、安全边界）、`docs/配置与部署.md`（环境变量、凭据格式、建库与迁移顺序、端口、手机访问、故障表、备份、升级、提交自检）、`backend/.env.example`、`database/.dbcreds.example`、`database/.appcreds.example`；`vite.config.ts` 开发代理 8000→8001 与启动器默认端口对齐。
- GitHub 私有仓库 `2230274247/ale-workbench` 已建，main 分支 278 文件与本地 tree SHA 完全一致（`51076428b65b59eafb4254ce559ee8a4fee1be8f`）。本机代理拦截 github.com:443（api.github.com 与 codeload 可通、github.com 直连与代理均失败），推送改走 Git Data API 写入；因 GitHub 将作者时间归一到 UTC，远端 commit SHA 与本地不同但树相同。后续本机恢复对 github.com 的访问后，首次 `git push` 需执行一次 `git push -f origin main`（内容一致，仅历史 SHA 不同）。
- 仓库保持 private；`reports/`、原始文件与数据库均未上传。


## 2026-11-11 阶段 9 移动网页版（/m 独立入口，电脑版零回归）
- 用户要求新增手机网页版并保留升级 App/小程序的路径，明确**不推翻现有电脑版**。新增并列入口 `/m`：独立 `frontend/src/mobile/`（MobileShell + 快录/历史/数据集/我的 四视图 + mobile.css，`m-` 前缀样式），共用同一 `/api/v1`、登录态与数据库；桌面版仅页脚加「手机版入口」链接。
- 手机快录：单列卡片、A/B/C 三源卡、ΔP 单值/区间、净减薄与 EPC 实时推算、存草稿/保存记录；编辑已有记录时只改第一组前 3 步，多余组/步骤保存时原样带回（防覆盖电脑端复杂结构）。历史为卡片列表+筛选+加载更多；数据集含导出、批量导入（上传原表→预览→勾选确认）与体检摘要（eligible_count/training_status/unit_audit）。
- 路由守卫：`/m` 未登录跳 `/m/login`（复用 LoginView，登录后按来源回 `/m/quick`）；`/m/login` 已登录跳快录。index.html 加 viewport-fit=cover、manifest、apple-touch-icon；`frontend/public/` 新增 manifest.webmanifest（start_url=/m/quick）与程序化生成的 SVG/PNG 图标（纯 zlib PNG 写入，无 PIL）。未加 Service Worker，避免缓存旧版。
- 验证：`npm run build`（含 vue-tsc）通过；Playwright(msedge, 390×844 移动视口, test 账户登录) 实测 `/m/login /m/quick /m/history /m/dataset /m/me` 全部零横向溢出、底部 tab 导航可用，截图与 check-results.json 在 `reports/mobile/`；1440×900 电脑版 `/quick /quick-dataset` 零溢出、页脚链接存在。唯一控制台 401 为登录前刷新探测，属预期。
- 手机实际访问待选型（局域网绑定 0.0.0.0 / adb reverse / 公网 HTTPS），见 `docs/ale_v2_2/05_mobile_web.md` 第 2 节；App（Capacitor 套壳）与小程序（uni-app 重写 UI + Bearer 登录改造）路径与工作量已写入同文档。后端无改动。


## 2026-11-11 阶段 8 批量导入支持「原表直接上传」
- 用户问「能否将 Excel 直接上传就导入」。原实现要求第 2 行逐字匹配 33/28 列表头，用户自己那份记录表极易 422。改为表头自动定位 + 按列名映射：任意工作表前 10 行内找到含 日期/材料/反应物A/A_Pulse 等列的表头行（优先「实验记录」表），列顺序、多余列、空格与换行、全角括号、`℃`、`▲P`、`N2(sccm)` 差异均不影响识别；缺列留空不推断。
- 无日期且无材料的行（合计/说明行）不再当错误行，计为 `skipped` 并在预览列出；预览响应新增 `sheet / header_row / matched_columns / skipped`，前端据实显示来源表与跳过行数。仍保留 SHA-256 预览指纹与人工勾选确认，不做无核对的静默入库。
- 新增 `test_stage3_batch_import_own_workbook_any_layout`：表头在第 3 行、工作表名非「实验记录」、列序整体倒置、混入无关列、表头写法含全角/空格、末尾合计行，要求 1 行可导入 + 1 行跳过 + 三源参数正确。独立测试库 `ale_workbench_test` 全量 `pytest tests/test_quick_v22.py` → 22 passed。
- 离线用真实文件验证：`ale-xlsx-20261111T055017.xlsx` 识别「实验记录」第 2 行 33 列、4 行实验且 A/B/C 三源齐全（O3/HF/TMA）；空模板与 28 列兼容文件同样识别为 33 列（用户手改模板已含反应物C）。vue-tsc EXIT=0，`npm run build` 通过，`frontend/dist` 已更新。
- 导出侧无改动；用户 13:50 的新导出已确认 I 列=反应物C(TMA) 与 U–X 的 C 组参数落位正确。


## 2026-11-11 阶段 7 模板扩至 33 列（含反应物C），修复导出「三个源只出两个」

用户把下载的模板手工改成 33 列（在「工艺参数」插入反应物C，`核心工艺输入` 顺延为 J1:Y1），并指出导出文件里网页端明明有 3 个源、导出只有 2 个。**只读诊断**：用户导出文件 `ale-xlsx-20261111T052432.xlsx` 每条 Run 的 payload 实有 3 个启用源 `O3 / HF / TMA`，但主表仍是旧 28 列结构，`leading_steps(run,count=2)` 只取前两步 → 第三个源（TMA）无处可落。

**修改文件**：
- `backend/app/quick_dataset.py`：`HEADERS` 扩为 33 列（反应物C 在 I，`C_Pulse/C_ΔP/C_Purge/C_Wait` 在 U–X，Cycle 至 Y，其后整体右移）；新增 `HEADERS_28` 仅用于导入兼容；`MAIN_GROUPS` 重划为 `A1:D1 / E1:I1 / J1:Y1 / Z1:AA1 / AB1:AC1 / AD1:AG1`；`leading_steps()` 默认取 3 步；`main_table_rows()` 输出 C 组五列；`detail_tables()` 主表映射标注改为 A/B/C/D 及以后；`mapping_version=competition33/user-confirmed-4`；manifest 警告同步；备注列宽改为第 33 列。
- `backend/app/quick_batch.py`：`build_row()` 按 A/B/C 三组读取；预览表头校验同时接受 33 列新模板与旧版 28 列模板（旧文件缺 C 组列即留空，不推断）；模板下载文件名改 `ale-33col-template.xlsx`、列宽第 33 列。
- `frontend/src/views/QuickDatasetView.vue`：模板/导出文案改 33 列（含反应物C）、说明旧 28 列仍可导入；批量预览表增加「反应物C」列与 `reactantC()`。
- `backend/tests/test_quick_v22.py`：导出断言改为 33 列、按列字母判定不再依赖行顺序、新增 C 组落表断言；批量导入用例改为 33 列并断言 3 个步骤、导出主表 C 组五列有值；**新增 `test_stage3_batch_import_accepts_legacy_28col`**（旧 28 列文件仍可导入）。
- `docs/ale_v2_2/04_excel_mapping_contract.md`：28 列口径全部改为 33 列，并写明旧模板兼容与合并区范围。

**真实验证**（证据 `reports/stage7_33col_reactant_c.log`）：
- 独立 `ale_workbench_test` 库事务回滚 `pytest tests/test_quick_v22.py -q` → **21 passed**。
- 新模板 `reports/ale_33col_template.xlsx` 与用户手改模板**逐字比对通过**：33 列、表头全等、分组行全等、6 个合并区完全一致（`A1:D1 / E1:I1 / J1:Y1 / Z1:AA1 / AB1:AC1 / AD1:AG1`）。
- 用用户导出文件的真实 payload 重算：`反应物A=O3 / 反应物B=HF / 反应物C=TMA`，`A_Pulse=110 / B_Pulse=800 / C_Pulse=1500 / C_ΔP=200 / C_Purge=35 / C_Wait=3`，主表 33 列（预览 `reports/stage7_export_33col_preview.xlsx`）。
- `vue-tsc --noEmit` EXIT=0；`vite build` EXIT=0（1m19s）；`frontend/dist` 同步 71 文件、逐 SHA 通过，旧 index 备份 `reports/stage7_dist_index_before.html`，清单 `reports/stage7_dist_sync.json`。

**边界**：无表结构变更、无迁移、无生产数据写入；生产 payload 的第三个源本来就在库里，本次只是主表不再丢弃它。后端代码需重启服务生效；浏览器需 `Ctrl+F5` 强刷。真实浏览器与正式账户验收仍待用户本人。

## 2026-11-11 阶段 6 端到端闭环验证（真实 HTTP 服务，批量导入→导出→往返保真）

用户要求继续完成未完成事项。任务清单中阶段 2–5 均已实现并通过隔离库测试，剩余未做的是**对运行中的真实服务做完整闭环验证**。本次在独立 `ale_workbench_test` 库上起临时 uvicorn 实例（127.0.0.1:8010，验证后已停止），用真实 HTTP 完成全链路。

**验证步骤与真实结果**（证据 `reports/stage6_e2e_roundtrip.log`）：
1. 测试库插入临时验收账户 `e2e_batch_admin`（purpose=testing，应用自身 Argon2 哈希；生产库未触碰）。
2. 登录 200 → 建材料 Al2O3 201 → 下载 28 列模板（6 个合并分组，SHA `cf8b04dc…`）。
3. 构造 4 行数据（3 行有效 + 1 行材料不在目录）上传预览：**3 行通过、1 行报中文错误「材料不在你的材料目录中，请先在快录页创建」，未写半条记录**；ΔP 区间 `70–100` 正确解析为 min/max。
4. 负面测试：篡改预览行回传 → 422「预览数据已变化」；确认后重复导入同文件 → 409「实验ID 已存在：E2E-001… 请在 Excel 中修改后重试」，系统未自动改写。
5. 确认入库 201，创建 3 条 Run（5404/5405/5406）。
6. 导出 XLSX（6 个工作表：实验记录/记录明细/源步骤明细/结果明细/映射说明/完整附加字段），**33 项列值逐项 PASS**：日期/批次ID/样品ID/材料/设备/反应物A(TMA)/反应物B(HF)/温度275/压力/载气/A·B 八参数（含 B_ΔP='70–100' 区间）/Cycle/膜厚前后/结果标签/数据质量中文值域/用于建模/备注，全部与导入值逐值一致；EPC 派生值 0.75 与 1.0 正确（(前−后)×10/Cycle）。
7. 主表「实验ID」按已确认口径写系统 `Q-…`，外部实验ID E2E-001/002/003 在「记录明细·外部实验ID(原始标识)」列完整保留，映射核对通过。
8. MySQL 显式列投影核对：`quick_runs.r1_temp_c=275/equipment='ALD-01'`、`quick_steps` 源/参数/区间 min·max、`quick_results` 3 行，全部落库。

**边界**：全程仅隔离库；生产库、生产服务（8001）、生产原件、用户 Excel 均未触碰；临时服务 8010 验证后已停止（复测 000 无监听）。**真实浏览器操作与正式账户验收仍待用户本人执行**（双击「启动工作台.cmd」+ `Ctrl+F5` 强刷）。

## 2026-11-11 全字段入口 / MySQL 显式列 / 批量导入（用户实报「没有按钮给我填写」后完成）

用户反馈网页端没有可填入口，明确要求「表格字段都在网页端给一个入口」「可以修改数据库字段」「前后端逻辑完整实现」。三项确认：保留现有布局缺哪补哪；MySQL 补显式列并改后端接口与前端传回数据；页面定位由截图确认。

**只读诊断**：截图确认是 `/quick`「新建实验记录」页，但截图里缺阶段 2 已加的「外部实验ID／批次ID」，说明浏览器标签页仍是旧 JS；实测服务端 `frontend/dist` 的 `index-B2EDjxLS.js` 确实引用含新字段的 `QuickRecordView-xl7uzWyK.js`。原始 TCP 复测发现 **8001 当时无监听、进程 62528 已退出**（HTTP 502 来自本机代理而非后端），正好是数据库变更窗口。MySQL 核查：`quick_runs` 仅 9 列，所有新字段只在 `payload` JSON 里，外部 SQL 查不到。

**修改文件**：
- `database/migrations/0016_quick_excel_fields.sql`（新增）：`quick_runs` 加 13 个实验级显式列；新建 `quick_results`（结果级 1:N）与 `quick_steps`（源步骤级 1:N）。只增不删、payload 不动。
- `database/migrate.py`：新增 `validate_quick_excel_fields()`，0016 应用/状态校验与 `ale_app` 授权。
- `backend/app/quick.py`：新增 `project_fields()`，在 `store()` 同一事务把 payload 确定性投影到新列/两表；**迁移未应用时静默跳过**，服务不因缺列崩溃。
- `backend/app/quick_batch.py`（新增）：`GET /quick/batch/template`、`POST /preview`、`POST /confirm`；预览无状态（行 + SHA-256 指纹回传），确认重新逐行校验并在请求事务内批量建记录，失败整体回滚；表头逐字匹配 28 列、材料必须已存在、ΔP 单值/区间、数据质量值域映射、重复 ID 409 提示改 Excel、EPC 只读自动算。
- `backend/app/main.py`：注册 `quick_batch.router`。
- `frontend/src/views/QuickDatasetView.vue`：新增「批量导入实验记录」区（下载标准模板／上传预览／逐行核对／确认入库），导出说明同步更新。
- `backend/tests/test_quick_v22.py`：新增 `test_stage3_batch_import_template_preview_confirm`（模板→预览→确认→回读→显式列→重复 ID 409），并给 `test_stage2_field_coverage_roundtrip` 增加显式列断言。
- `docs/ale_v2_2/04_excel_mapping_contract.md`：删去「不批量导入」旧口径，追加批量导入合同。

**生产库变更（用户明确授权加字段）**：`migrate.py --database ale_workbench` 应用 0016，自动备份并逐值校验「57 行原值保持」；随后从 payload 确定性回填显式列与两张表，结果 `RUNS 4→4 / PAYLOAD_UNCHANGED True / RESULT_ROWS 4 / STEP_ROWS 20 / NONEMPTY_R1 4`（证据 `reports/stage5_backfill.log`）。`--status` 复验 0016 校验通过。**未重建库、未删列、未覆盖 payload、未自动清理生产数据**。

**验证**：独立 `ale_workbench_test` 库（0016 已应用）真实 MySQL 事务回滚 `pytest tests/test_quick_v22.py -q` → **20 passed**（`reports/stage5_pytest_final.log`）。首次组合验证里 `test_stage3_batch_import_template_preview_confirm` 因 `quick_steps` 查询未排序、断言依赖行顺序而失败 1 次，已改为集合断言并复跑通过；失败输出保留在 `reports/stage5_full_verification.log`，不计作通过。`vue-tsc --noEmit` EXIT=0；`vite build` EXIT=0（1m4s）；生产 `frontend/dist` 同步 71 文件、逐 SHA 通过、旧 index 备份 `reports/stage5_dist_index_before.html`、清单 `reports/stage5_dist_sync.json`；生成可直接填写的 28 列模板 `reports/ale_28col_template.xlsx`（28 列、6 个合并分组）。

**边界**：仅隔离库跑业务测试；生产库只做 0016 加列/加表与确定性回填；**未启停任何服务**（8001 当前无监听）；未修改用户 Excel 或生产原件。Windows 实机、真实浏览器与正式账户验收仍待本人执行。

**用户下一步**：双击「启动工作台.cmd」（默认 8001，启动器按源码/dist 指纹安全重启），浏览器 `Ctrl+F5` 强刷；在「数据集中心」可下载模板并批量导入，导出主表与三张明细表已补齐。若强刷后仍看不到新增输入框，请提供新截图。

## 2026-11-11 阶段 4 导出补齐（用户实报「导出依旧字段都没有出来」后追加）

用户从 `H:\ALE_AI` 启动服务导出 `C:\Users\Administrator\Downloads\ale-xlsx-20261111T040203.xlsx`，反馈主表字段仍为空。**只读诊断**：该文件 3 个 sheet、主表 4 行数据，13 列全空（批次ID、设备/腔体、反应物A/B、温度/°C、压力/Pa、A/B 共 8 列、均匀性、结果标签）；但「完整附加字段」里明确存有 `r1_temperature_c=275`、`r2_temperature_c=255`、`n2_flow_sccm=20`，以及 A 组 3 个启用源 `O3/HF/TMA` 及各自 Pulse/Purge/Wait/ΔP。即**网页确实填了、导出主表丢了**。根因是上一阶段只做了字段补齐（阶段 2），导出取数（阶段 4）尚未实施；且生产 `frontend/dist` 未重建，网页端新入口也不可见。

修改文件（2 个）：
- `backend/app/quick_dataset.py`：新增 `reactant/step_number/delta_p/leading_steps/model_flag/QUALITY_LABELS` 等映射辅助；`main_table_rows()` 把 28 列按已确认映射补齐（第 1 列→反应物A、第 2 列→反应物B、温度只写 R1、ΔP 支持区间、数据质量中文值域、用于建模「是/否」）；主表改用 `styled_sheet()` 复刻参照表 6 个合并分组与配色；新增「记录明细／源步骤明细／结果明细」三张仿原表风格的扁平表，承载第 3 列及以后（含反应物C）、R2、外部实验ID、工艺类型等全部网页字段；`manifest()` 警告与 `mapping_version` 同步更新为 `competition28/user-confirmed-3`。
- `backend/tests/test_quick_v22.py`：更新 `test_export_real_xlsx_json_wide_readiness` 断言（原断言温度/反应物A 留空，现改为有值且不依赖行顺序），新增对 6 组合并表头与三张明细表的断言。

命令与实际结果（证据 `reports/stage4_export_tests.log`）：
- 独立 `ale_workbench_test` 库事务回滚夹具 `pytest tests/test_quick_v22.py -q` → **19 passed**（1 个与业务无关的 starlette-anyio 弃用警告），15.90s。
- 用用户导出文件里真实 payload 走同一段 `main_table_rows/detail_tables/styled_sheet` 生成效果预览 `reports/stage4_export_preview.xlsx`：反应物A=O3、反应物B=HF、温度=275、A/B 八列参数全有、数据质量=待复核、用于建模=否；第 3 列 TMA 在「源步骤明细」5 行中。**仍为空的 6 列（批次ID、设备、压力、均匀性、结果标签、备注）是用户本来未填**，按「未知留空不补 0」保持空白，不是遗漏。
- `frontend/dist` 同步：从临时构建复制 **71 个文件**，逐文件 SHA256 校验全部通过；旧 `index.html` 备份至 `reports/stage4_dist_index_before.html`（SHA 前 `2e8a6ee0…` / 后 `f0db3340…`），旧 assets 保留（717→747）。清单 `reports/stage4_dist_sync.json`。

边界：未连生产库、未写正式账户、未启停任何服务、未修改用户 Excel 或生产原件；预览文件是隔离重算，**不是**服务端真实导出。`frontend/dist` 属生产资产变更，已备份并逐 SHA 核对。

**用户必须重启服务**：后端 Python 代码在进程启动时加载，当前运行实例仍是旧导出逻辑；双击「启动工作台.cmd」会由启动器按源码/dist 指纹安全重启（端口默认 8001）。重启后重新导出即可看到补齐结果。**Windows 实机与正式账户验收仍待本人执行**。

遗留：阶段 3 批量导入仍未实施；`docs/ale_v2_2/04_excel_mapping_contract.md` 原写「不批量导入」尚未更新；`/api/v1/quick/*` 契约外状态未变。

## 2026-11-11 实验快录字段全覆盖：阶段 2（补网页字段与后端模型）已实现并验证

需求与方案：用户要求 `/quick` 实验快照能填写参照 Excel 的全部字段、支持批量导入、导出不丢网页数据。经四轮只读核对与逐项拍板，定稿 `reports/实验快录_字段字典与批量导入方案_v2.md`（v1 保留历史）。**本阶段只实施阶段 2**；阶段 3（批量导入）与阶段 4（导出补齐＋明细表仿原表风格）尚未实施，不宣称已交付。

已冻结口径：主表保持 28 列结构不变；网页第 1 列源＋四参数 → 反应物A/A_*，第 2 列 → 反应物B/B_*；第 3 列及以后（含反应物C）进明细表；只 ΔP 支持单值/区间；`Cycle` 取本段有效循环次数；温度只读写 R1，R2 存库但进明细且非必填；所有 ID 由系统把控，原 Excel ID 原样收进明细表作为「原始标识」；导出按结果拆行，导入遇重复 ID 报错并提示在 Excel 中修改。

修改文件（4 个，无新增表／迁移／主键变更）：
- `backend/app/quick_models.py`：Step 新增 `delta_p_pa_min/max` 及区间校验（单值与区间互斥、双边界成对、下限不大于上限）；Environment 新增 `process_type/rf_icp_power_w/bias_power_w`；Result 新增 `result_label/use_for_model_override`；Run 新增 `external_experiment_id/external_batch_id`。全部经现有 `payload` JSON 与 `model_dump(mode='json')` 落库。
- `frontend/src/quick/model.ts`：同步默认值、`resultKeys`、`cleanNumbers`（新数值字段、空串→null）、`fieldName` 中文名。
- `frontend/src/views/QuickRecordView.vue`：新增外部实验ID／批次ID／工艺类型／RF-ICP／Bias 入口；设备腔体与腔体绝对压力由折叠区提到明面；ΔP 改为单值/区间两用输入（非法输入保留并定位）；结果标签、用于建模新增入口；总工艺时间与刻蚀速率按起止时间/膜厚自动推算，只读、不入库。
- `backend/tests/test_quick_v22.py`：新增 `test_stage2_field_coverage_roundtrip`，验证新字段真实 store/present 往返、payload 落库，以及三种非法区间 422 且无写入。

命令与实际结果（证据 `reports/stage2_field_coverage_tests.log`）：
- `vue-tsc --noEmit`：EXIT=0，0 诊断。
- `vite build --outDir /tmp/ale-stage2-build --emptyOutDir`：EXIT=0，38.29s 成功，保留既有 >500 kB chunk 提示；**生产 `frontend/dist` 未覆盖**（index.html mtime 仍为 2026-10-26 09:20，assets 717 文件）。
- `ALE_DB_NAME=ale_workbench_test ALE_REQUIRE_TEST_DB=1 ALE_ENVIRONMENT=testing ALE_INSTANCE_ID=ale-workbench-testing ALE_ORIGINALS_ROOT=H:/ALE_AI/storage-test/originals python -m pytest tests/test_quick_v22.py -q`：**19 passed** / 1 个 starlette-anyio DeprecationWarning（与业务无关），10.09s，真实 MySQL 事务回滚夹具。
- 另做 Pydantic 自检（未单独落盘）：单值与区间序列化正确；单值+区间并存、缺边界、下限大于上限三种输入均被拒绝。

边界：仅独立 `*_test` 库与事务回滚；未连生产库、未写正式账户、未启停任何服务、未修改用户 Excel 或生产原件、未覆盖生产 dist。以上通过**不代表** Windows 实机、真实浏览器或正式账户验收。

遗留与下一步：阶段 3 批量导入（模板下载→上传→逐行预览→人工确认→单事务入库）；阶段 4 主表 28 列按已确认映射补齐＋明细表仿原表风格，需同步更新 `test_quick_v22.py:108` 的「温度/反应物A留空」断言但不得弱化事实边界；`docs/ale_v2_2/04_excel_mapping_contract.md` 原写「不批量导入」需改为新合同；`/api/v1/quick/*` 是否补 OpenAPI 契约属独立决策。阶段 4 按 D10 主表「实验ID」写系统生成值，外部实验ID 进明细表。

## 2026-10-20 样品—实验双向关联与操作修复：代码、真实MySQL、浏览器完成，Windows本机待确认

本轮复用现有 samples/process_samples/sample_transitions/process_steps，无新增表、无0014迁移。完成四项：样品创建内联新建批次并保留表单；样品编号可编辑且历史关系按sample_id保持；执行详情显示逐片批次、本次/累计循环、装卸节点与测量，样品详情新增“参加过的实验”；计划/执行列表恢复生命周期入口和批量清理未使用草稿。场景A同一样品两次执行保留两条独立记录，累计仅汇总已记录值；场景B五片同腔按各自full_ale_cycles与load/unload步骤显示，设备总循环不冒充逐片；缺失循环显示“未记录”，不推断。

代码：backend/app/participation.py（新增）、records.py、experiments.py、schemas.py、lifecycle.py；frontend RecordsView.vue、ExperimentWorkspace.vue；database/setup_test_env.py（新增）、purge_test_data.py环境闸门、tests/conftest.py禁止非_test库跑隔离测试；契约与生成模型同步。计划/执行删除允许管理员或记录所有者，仅在无依赖草稿时；批次/样品删除仍限管理员，样品作废规则不变；任何删除均先走impact预览、preview token、版本校验与审计，不级联科研证据。

测试环境：已创建独立库ale_workbench_test（43表/6视图/13迁移/0用户）和storage-test/originals；测试命令设置ALE_DB_NAME=ale_workbench_test、ALE_ORIGINALS_ROOT、ALE_ENVIRONMENT=testing、ALE_INSTANCE_ID=ale-workbench-testing、ALE_REQUIRE_TEST_DB=1。端口不同不构成隔离；测试账户仍是用户级隔离，只有独立库/原件目录才是存储级隔离。

验证：新增后端专项5 passed（reports/sample-link-tests.log），真实Chromium 3 passed（reports/sample-link-browser.log），回滚后43表与测试原件一致；契约通过（reports/sample-link-contract.log）；构建通过，index SHA256 b70a3f06f3735217348fa0052a2cd37f94b4035db529da6318829ac76b262224（reports/sample-link-build-manifest.json）。回归：round8工作流/网格/首页+导入39 passed；phase2/phase4/lifecycle 47 passed、1既有失败；phase5收尾/phase3管理/账户用途63 passed。既有test_phase4.py::test_archive_is_idempotent_and_delete_is_blocked_by_runs仍失败（2026-10-19同），与本轮无关。Windows本机需确认内联批次、改名、双向跳转与删除预览。

详见reports/样品实验双向关联与操作修复方案.md第6节。


## 2026-10-20 三账户与科研数据隔离：代码、真实MySQL与浏览器验证完成，本机待确认

最新《三账户与科研数据隔离任务书》在本轮实施。复用现有 admin/operator/viewer 与 owner/operator 归属，新增账户用途 management/research/testing；不重建用户系统、不新增多租户。迁移0013已应用（users/invitations.account_purpose及组合约束），迁移时366行既有字段值保持。按用户明确授权，旧测试账户2个、业务359行、对应原件5份已清理；清理前快照backups/before_migration_20261020T043104552697Z（43表388行）。当前users=0，初始化状态，未创建默认密码。

代码：后端data_visibility.py（新增）及auth/users/schemas/imports/measurement_management/scientificanalysis/transitions/ai/ai_tools/config/db；前端api/auth/App/main/sessionTypes/AppShell/AIAssistant/experiments.model/Records/Imports/AISettings/Users共12文件；契约、Python模型和校验器同步。功能：导入光学模型按批次过滤；失权历史分析404；测量/原件引用最小投影；测试账户默认禁止外部AI发送；按用户金额/token预算；/ai/usage/me仅本人；顶部显示用途/环境/数据范围；换号清理旧请求与草稿。

操作：登录页初始化 -> 用backend/.setup-code由本机创建admin（management，自设密码）-> 成员与邀请分别邀请科研operator/research、测试operator/testing -> 受邀人邀请注册自设密码。管理员全局视图有明确标识；科研/测试仅本人数据。测试环境建议ALE_DB_NAME=ale_workbench_test、ALE_ORIGINALS_ROOT独立、ALE_ENVIRONMENT=testing、ALE_INSTANCE_ID独立；端口不同不等于隔离，本轮未创建。

验证：专项90 passed（reports/account-isolation-backend-special-tests.log）；真实Chromium三账户2 passed（reports/account-isolation-browser.log），回滚后43表一致、0原件；契约通过（reports/account-isolation-contract-db.log）；构建通过，index SHA256 1fc4293a5ce6febc8a04c9b029516a23ccf785a30dc2595bb021cd8d3ba82fef；回归分组见reports/account-isolation-regression-*.log。已知既有失败test_phase4.py::test_archive_is_idempotent_and_delete_is_blocked_by_runs（2026-10-19同失败，归档后删除语义旧断言，与本轮无关）。Windows本机初始化/登录/邀请及服务重启待用户确认。

详见reports/三账户与数据隔离交付报告.md。


## 2026-10-20 产品最小化任务：P0已验证，P1仅方案待评审

最新《产品定位与最小化改造任务书》授权两项P0修复及P1设计，取代此前完全暂停状态；不授权大范围重构。默认工艺表已改为源／脉冲(ms)／吹扫(s)／等待(s)／压差(Pa)五行×#1–#5，25格空白，不预填科学值，只有输入才创建步骤；温度、模板和复杂历史保留在高级视图，不截断、不换算。最后一步有“保存并查看实验”，无测量可结束整理，保存修改后打开同一计划/执行，不把记录标为科研完成。尚未交付P1统一详情，现有跨页问题如实保留。

产品修改文件：frontend/src/components/ProcessGrid.vue、frontend/src/experiments/processGrid.ts、frontend/src/views/ExperimentWizardView.vue；测试为test_product_p0_matrix_browser.py、test_round8_grid_browser.py、test_round8_workflow_browser.py。真实原始实验数据只读，未增表或迁移。基本操作：空白矩阵直接填格→保存；高级字段点“高级编辑”；最后页点“保存并查看实验”，失败保留输入并定位需处理区块。

代码完成：是。真实MySQL回归：通过，事务夹具回滚后43表及5原件指纹一致。最终组合构建：npm run build（vue-tsc + Vite）通过，26.89s；共享构建矩阵6 passed，结束7 passed/5 deselected，契约2 passed。命令、修改与问题详见reports/产品重整方案.md第10节及reports/product-p0-combined-*.log、product-p0-contract-final.log。专项20/8/12与这些复验存在覆盖，不相加。最新index SHA256：1944899e7e2eb6a217ee1419e38a6f8fa9912e70626e220ed418d86b73500262。大chunk提示保留；早期超时契约运行不算通过，已单独复验通过。Windows本机用户确认：待办；服务未在本次启停。

只读产品审查已输出reports/产品重整方案.md，包含五痛点、全部路由取舍、三个ASCII低保真、点击路径估算、参考仓库具体文件及许可、最小切片、非破坏恢复建议、至多三个决策。未实施P1，不初始化Git，不引入框架或AI模块。到此停止等待用户评审。第七步根因为缺失清楚UI终点；既有生产记录证明前面有保存，历史是否误建重复无法判定。

## 当前最高优先级：产品方向调整，安全停靠（2026-10-19）

已阅读《ALE 实验工作台｜第八轮方向调整与产品重整指令》。这属于第八轮变更请求，不启动第九轮。当前暂停新增业务开发、完整向导继续扩张、新增导航页面及大型模块；产品方案审查也须等待用户确认。下方“第八轮最终证据”仅记录已完成实现，不代表新方向已获认可。

停靠状态：四阶段既有代码已落盘，应用／API1.8.0，已列构建与基本回归完成；最后故障恢复专项为后端9 passed、共享构建浏览器7 passed、契约2 passed。最新共享index SHA为a74ba150e1f4f73b7d6fdef2d344e25cc50c6b616c7682dacfd63580c72e9c32。当前目录没有.git，不能报告分支或Git工作树差异；未丢弃代码、未执行回滚。可见会话中无其他代理会话，Linux工作区无pytest／Vite／迁移／uvicorn活动任务；Windows服务实时状态未在本次核验，也未启停。

数据库历史：0011／0012此前已生效，保留其迁移、备份与日志；本次停靠不执行数据库写入或迁移，不修改原件和审计。Windows实机重启、跨进程持久化与live DeepSeek仍待验，暂不自动推进。没有新的进行中源码改动或需要强行打断的迁移。

待用户确认的下一步：仅开展只读产品审查，以“记录一次实验、回顾一次实验、查看实验数据”为目标盘点真实页面／路由／表单／按钮，形成一份reports/产品重整方案.md。方案包含减法清单、三入口及旧路由映射、三个低保真页面、两个任务点击路径、实施切片和至多三个产品决策；原型不接生产写接口。该方案获确认后才考虑业务改造，本次不创建方案或原型。

## 当前入口：第八轮最终证据（手册1.13第58节；应用／API1.8.0，2026-10-19）

只持续更新本文件、reports/功能实现与操作手册.md、reports/第一轮开发报告.md、启动说明.md。Round8代码与已列本地测试、契约及最终共享构建已完成；Windows实机和真实服务商验收独立待办。最新P1恢复复验已通过，当前构建及修复明细见本文件末尾“最终故障恢复复核补记”。下方第七轮INTEGRATION PASS保留其历史语境。

- [x] 阶段一二维网格：计划／执行／创建共用矩阵；步骤列、自定义行改名、组复制移动删除、模板副本、自由源名称建议、独立值／单位、旧参数权威与只读核对、实际继承清值及计划创建部分失败恢复均有专项。stage13-backend-audit为18 passed；matrix-browser 2 passed／4 deselected；inheritance-browser 2 passed／4 deselected；stage1-final-dist-browser 3 passed／4 deselected。运行重叠不相加。
- [x] 阶段二生命周期：四类真实影响预览、隐藏依赖不披露、归档／有证据恢复、终态作废、管理员无依赖草稿删除、显式选中未使用样品及原操作回执恢复已实现。lifecycle-backend-final 15 passed；delete-final 20 passed；void-final 40 passed；browser-complete 3 passed且JS错误[]；migration-replay 1 passed／15 deselected，各自列数，不合计。早期失败与无终态日志仍保留历史。
- [x] 阶段三导航／首页：当前组始终可见、账户折叠偏好、图标栏及390导航；首页真实待办／最近实验／最近数据／统计独立重试。dashboard-backend 9 passed；nav-dashboard-browser早期7 passed；stage3-nav重跑4 passed／3 deselected；stage3-final-dist首页重跑3 passed／4 deselected。9与18、7与4／3存在覆盖重叠，不累计。
- [x] 0011／0012已应用日志：只增既有表生命周期元数据／约束和计划archive_previous_status，仍43表，不修改旧迁移或回填科学事实。0012备份before_migration_20261019T075049087536Z、existing rows199、原字段181行保持；migration-final记录0011=14:52:17、0012=15:50:52。自动提交DDL与测试回滚不同，本次不运行迁移。
- [x] 阶段四及工作区：workflow API／浏览器5 passed；workspace 19项分4＋4＋4＋7全部通过，0 xfail，含stage定点打开、非法参数回0、stage-only保留草稿、七节点URL、归档恢复／作废筛选及删除预览。七阶段持久事实和关闭重开已验证；多请求保存仍非整体事务，完整导入／分析自动关联不作超范围保证。
- [x] 1.8.0契约专项最新末段通过：round8-contract-final.log在初次LogStatus未定义及随后响应夹具失败后追加修复重跑，最终strict parity/schema PASS；117路径／178操作／285 schemas，121 implemented／57 planned，241 Python模型JSON schema可构造，frontend contracts字节一致，运行期121操作parity通过。启动器已同步1.8.0及26路径／27操作静态检查通过，未执行PowerShell。--no-db不证明数据库验收。
- [x] 最终共享build：round8-final-shared-build.log显示vue-tsc --noEmit && vite build，3810模块、20.03s成功；54个实际dist文件，index SHA256 `4dd4cfe016261117d20a3ab4e5967b124233492530d90a5f7e771382a489c0c6`。41份源码和4份构建输入与实际构建快照逐文件一致，详见round8-final-build-consistency.log；不再以早期空typecheck文件推定结果。
- [x] 导入／parser／分析／AI tools回归84 passed／1 skipped（63＋9＋12三组，缺真实ZIP语料）；离线AI全量138 passed／0 skipped（三组各46）。六项预算测试改为相对基线断言，未改生产AI；4532 charged_tokens、0 reserved、2请求／3 daily slots账本保留。重复定向6 passed已包含在138中。最终日志及4张工作区截图归档reports/round8-final-*，详见手册58.6。
- [ ] Windows实际8001可信新PID／创建时间／服务验收、保存后独立GET跨进程重读、Key ACL仍待本人执行；本次未运行PowerShell或启动／停止任何服务。
- [ ] live DeepSeek Key、真实通用测试及另经本人同意最少元数据后的tool_calls／origin=model权限／追问／usage／账单待验；分析AI仍仅准备元数据，无真实模型成功证据。

**保护边界**：沿用既有5原件／970151字节、5唯一SHA／10直接引用基线；所列测试日志43表／5原件指纹相等仅证明各回滚用例前后，排除自增计数器，不证明运行间连续无变化。旧16→5的11对象与17→16变化原因仍未知。无原件恢复、删除或新盘点。真实RGA／完整XPS、实际双worker提交结算／跨午夜等前轮边界仍保留。操作细节、每次运行及已知缺陷统一见手册58节；本次文档核对不冒称新跑业务测试。

---

## 第七轮历史入口：A–G 交付核对（手册1.11；应用／API1.7.0，2026-10-19）

当前统一操作入口为《功能实现与操作手册》第57节；本文件后文各轮checkbox和测试计数只代表对应历史，不累加为当前完成率。仅持续更新本进度、现有手册及现有开发报告，没有新建报告。

- [x] A：分组／账户导航偏好、桌面／窄屏及助手弹层保护已实现；phase7-nav-browser 2 passed，JS0。
- [x] B／C：AI停用状态先测试、模型真实返回元数据／未知项、错误状态与样品页批量入口；operations后端9 passed、浏览器3 passed，均含共享用例，不按功能重复计数。Provider为合成，20片／冲突保留为事务内验收。
- [x] D–F：自由分类流程网格、嵌套组、值／单位独立、模板副本、计划→实际清值、旧参数只读和权威快照、测量／流转等引用冻结保护已实现。0010增量迁移已应用，原106行字段保留。已有42／110+2skip／6日志互有重叠；最新交接47API／9定向亦重叠，不相加。最新一轮复核补齐：快照权威性显式标注（`parameter_source`、`legacy_parameters`、`legacy_parameters_status`、`parameter_conflict`），旧字段保留可查且不再静默冲突；历史保护扩展到父记录、步骤增删改、绑定和网格保存；新建脉冲默认ms，旧秒值不改写；旧快照转换补齐时长／循环／累计／分压／发生器／等离子体／自定义参数。
- [x] G：/analysis正式／预览同算法1.1.0、实际坐标Mapping／趋势均值、三循环独立、明确同样品同模型配对、PNG／JSON、显式保存／来源复核已实现；final-backend 7 passed，final-browser 2 passed，真实4／81点可信专项通过。不同模型允许并列，差值422。
- [x] 契约1.7.0：109路径／170操作，113 implemented／57 planned／243 schemas；契约校验、模型生成、Swagger与运行期113操作全量parity通过，43表和10个已应用迁移SHA只读核对通过。启动器关键18路径／19操作。
- [x] 最终集成关闭（round7-integration-final.log 末段 INTEGRATION PASS）：先前两处parity失败均为校验夹具本身不合规（中文自定义参数键不满足 `^[A-Za-z0-9_]{1,64}$`；`parameter_snapshot={}` 不满足必填 `step_type`），不是运行期或契约缺陷，已按真实约束修正夹具后重跑通过。定向68 passed／1 deselected覆盖修复后的两项旧断言，不与历史470分组相加。vue-tsc 0诊断；vite build成功，dist/index.html SHA256 `e74d866c…e03fb7`（趋势图坐标轴留白微调后重建）；contracts.d.ts与生成api.d.ts字节一致。43表／5原件回滚核对一致。
- [ ] Windows本人A–G启动与实操、可信8001实际新PID／时间、跨进程独立GET持久化、Key ACL均待验；未执行PowerShell，不宣称服务常驻。未知8000／8001监听者不可按端口或进程名终止。
- [x] 启动器写入就绪记录崩溃已修复（2026-10-19 本机实报）：旧版把 `$null` 传给 `File.Replace` 的备份路径参数，Windows PowerShell 转成空字符串后抛“路径的形式不合法”，发生在服务已通过全部检查之后，后端 1.7.0 已启动但无可信记录。现改为显式 `.bak` 备份路径原子替换，并新增严格的中断记录接收（项目根、backend根、端口、PID、创建时间、可执行文件、命令行、启动链、schema、nonce、版本、64位指纹及 verifiedUtc 全部匹配）。tree-sitter 0错误；Python语义模型复现旧异常并通过8项拒绝用例。**Windows 实际重跑仍待本人执行**。
- [ ] 真实DeepSeek Key／实际tool_calls／origin=model来源权限／账单待验；通用测试通过也不证明工具协议。科学分析工具仅准备元数据，live_ai_registered=false。

**原件当前基线：5份／970151字节、5唯一SHA／10直接引用，当前孤儿／引用缺件／大小不符均0。** 引用现有开发报告2026-10-19只读审计，本次未重读DB或原件。旧16→5的11对象具体变化事件／人／时刻／原因未知；历史17→16另未结。不能归因安全GC或agent误删；未恢复、删除、覆盖原件。测试前后43表／5原件指纹相等只证明所列边界。

手册57节逐项写明入口、按钮效果、字段／单位、权限／错误、状态矩阵与Windows8001命令。代码、后端、浏览器和Windows状态独立列出。此前真实RGA／完整XPS解析、实际双worker提交结算、跨午夜与第56节真实模型账务验收仍待补。

---

## 第五轮开发清单（2026-10-16，按本轮提示词跟踪）

本节保留第五轮主体检查点，最新准入与第六轮状态见本文顶部；后文保留前四轮历史。`[x]` 表示该条已完成并有相应核查证据；`[ ]` 表示未完成。代码实现、数据库集成、浏览器验收分别打勾，不以“代码已写”代替“功能已验收”。每完成一项立即更新。当前第五轮整体状态：10项需求的代码实现、集成与已列范围自动化验证已完成；最终构建指纹复核及源码缓存清理已完成。Windows本机持续启动／用户正式操作、真实RGA与完整XPS仪器语料及下列明确列出的界面边界仍待验收。该检查点操作对应手册第40–47节，最新操作见手册1.8第48–51节，旧轮手填关联ID说明保留为历史。

### 1. 批次删除失败：说明依赖并提供归档

- [x] 检查后端删除保护：现有 `protect_delete` 对全部外键及多态关联逐一检查，但遇到第一条依赖就返回英文通用 409，未显示关联类型和数量。
- [x] 收到批次删除报错截图：批次编码为“1”，提示 `Scientific dependencies prevent deletion`；截图作为复现依据保存于本轮上下文。
- [x] 真实MySQL只读诊断：batch_code=1对应batch_id=778，status=active、row_version=2、archived_at=NULL；直接依赖samples=2，计划／执行／仪器数据／来源／附件／问题关联／光学模型均0。证据为本session outputs/batch-archive-diagnostic-sha.log，未写该生产批次。
- [x] 隐藏依赖修复：全局完整性检查仍阻止删除，只披露可见类型和数量；隐藏依赖统一提示「另有受权限保护的关联记录」，不披露其类型／数量。已核对records.py、experiments.py及6项新增参数化回归；任务83交接为65项通过，原始65项运行日志未在项目／outputs留存，本次未重跑，不将交接计数伪称新日志证据。
- [x] 后端返回中文依赖类型和数量，版本校验独立处理；未实现逐条依赖记录导航，不能将数量提示称为记录入口。
- [x] 批次列表／详情归档入口与确认框完成；archived_at独立于status，样品／计划／步骤和历史关联保留，列表／详情标记与时间重载后可见。
- [x] 批次专项桌面／窄屏各2例：依赖DELETE409显示样品7／计划1，取消无写入、旧版本归档409、读新版本重试200、成功／失败反馈持续可见；owner operator／admin归档、viewer403及其他operator404均通过。归档后历史与业务状态保持；空记录删除由既有规则／回归覆盖，未把真实生产批次删除。

### 2. 实验计划创建失败：定位真实关联错误

- [x] 核对路由存在：`POST /plans` 已注册；计划创建会对批次执行存在性与所属权限校验。
- [x] 核对截图：创建计划时手填批次 ID“1”，返回 `Resource not found`；不能仅凭截图断言最终根因。
- [x] 检查现有运行日志：当前 server.log／stdout 无失败记录，stderr 仅启动信息，无法回溯该请求完整链路；不编造请求日志证据。
- [x] 真实只读诊断：batch_code=1对应batch_id778，id1不存在；plans/tools均0行。与源码引用校验共同定位编号／主键混用，未恢复缺失的原请求日志，也未补造生产对象；原截图用户完整权限链未能回溯。
- [x] 修复关联选择与服务端错误提示，保留用户输入；不存在／不可见对象要给出能解决问题的说明。
- [x] 实际API与桌面／窄屏浏览器按命名批次创建计划201；隐藏／不存在引用统一404、输入保留等服务端规则有回归。
- [ ] 计划编辑的全部关联切换／无权限错误界面组合尚无逐项浏览器证据，保留专项补验。

### 3. 实验执行删除与归档

- [x] 核对现状：后端已有执行 DELETE，但前端没有入口，且现有依赖保护会阻止含步骤／绑定的记录直接删除。
- [x] 前端执行删除与归档按钮、后端、迁移及联调已完成；空执行DELETE204、依赖409、归档200后reload保留快照／绑定。
- [x] 明确并实现删除策略：样品流转、正式测量、外部映射等科学依赖必须保护；不能把数据库级联当作删除授权。
- [x] 增加执行归档后端、增量数据库字段和返回数据，保留执行结果、日志状态与全部关联。
- [x] 空执行DELETE204、含步骤／绑定DELETE409、含流转依赖保护、历史归档／权限／CAS由API与回归覆盖；归档200后保留快照与绑定。
- [x] 执行归档标记、精确时间及原log_status在toast消失、服务stop/join/start和reload后仍保留，两宽度通过；同app／同回滚连接，非Windows重启。
- [ ] 含测量／外部映射等每种依赖的删除与权限／旧版本界面组合尚未穷尽。

### 4. 简化执行创建与关联对象选择

- [x] 前端已移除执行模式输入；新执行内部使用兼容的 `other` 分类，历史分类保留。
- [x] 前端已将计划／批次／设备手填 ID 改为显示名称的选择器，样品提交去重。
- [x] 前端已移除 O₃ 预处理和 HF／TMA 专用执行输入，保留旧记录展示能力。
- [x] 补齐设备选项接口，核对选择器的搜索、已有值回显、分页和权限隔离。
- [x] 验证从计划进入时继承批次与步骤结构，计划值和实际记录保持可辨，后续模板编辑不影响历史。
- [x] 浏览器完成“选计划／批次／设备 → 创建执行 → 查看关联名称”的完整流程。

### 5. 执行创建失败：关联、权限、参数、约束联查

- [x] 核对截图：计划／批次／设备均手填“1”，失败为 `Resource not found`；现有计划／批次／化学体系／样品的可见性校验均可能产生 404。
- [x] 在真实 MySQL 中核对每个关联对象，定位具体失败字段与约束，而非统一归咎于网络或前端。
- [x] 验证最小无关联执行与有效关联执行均可创建，失败时事务整体回滚。
- [x] 保留服务端权限检查，新增字段级中文错误及请求追踪日志，避免泄漏其他用户记录。
- [x] 命名关联创建201、最小无关联创建、成功反馈、请求中防重复与失败输入保护已由现有browser／API覆盖；清空计划取消保留两条草稿、确认清除继承步骤及映射，独立步骤POST201且plan_id／plan_step_id为NULL，两宽度通过。
- [ ] 创建执行各关联字段的无权限拒绝界面仍需逐项补验；后端404不冒称全部UI已点击。

### 6. 样品绑定去除特定化学体系字段

- [x] 前端已移除 O₃／HF／TMA 专用绑定输入，沿用可搜索单选／多选样品入口。
- [x] 核对当前绑定字段：样品选择、腔体位置、完整ALE循环数、对照与角色备注；未触碰的历史专用字段保留，绑定不改样品状态／不等于装载，装卸进度来自历史。
- [x] 单条／批量绑定由新旧流程验证；同批次／权限／重复绑定由API规则与回归保护，绑定不改变样品状态。
- [x] 两宽度验证真实并发绑定409→读取失败503保留冲突锁与输入→读取成功200只移除已绑定ID→剩余ID重试201；公共属性完整保留，完整ALE循环数按0–4294967295整数提交。
- [ ] 单条绑定编辑与所有跨批次／权限组合的逐项界面操作尚未穷尽。

### 7. 通用步骤、参数组与可复用模板

- [x] 新增 `ParameterGroupsEditor.vue`，支持源、脉冲、吹扫、等待、压差参数组及独立温度，可增加组／字段并改名称、值和单位。
- [x] 前端已接入计划／实际步骤编辑；任意自定义类型映射旧兼容分类 `other`，旧参数保持可读。
- [x] 新增 `backend/app/step_templates.py`，实现模板列表／创建／更新／删除、所有权隔离及版本检查。
- [x] 套用模板使用深拷贝快照；计划结构转为实际步骤时清空参数值，编辑旧步骤未触碰的历史参数不随保存被清除。
- [x] 7 项隔离单元测试通过；专项前端类型检查和临时生产构建通过。该结果不替代真实 MySQL 和浏览器验证。
- [x] 增量迁移新增 MySQL 模板表及计划／实际步骤 `parameter_snapshot`，注册路由并同步请求模型。
- [x] 实际 MySQL 验证模板 CRUD、权限、冲突、JSON 精度与历史快照隔离。
- [x] 每宽度两次停止／join旧Uvicorn并启动新server后重读类型／组／名称／单位／模板快照；同app同rollback连接有效，不代称全新OS进程或Windows重启。
- [x] 浏览器创建自定义步骤、第二组参数、单独字段并保存，修改模板后核对旧执行不变。

### 8. 删除暂存导入任务与安全清理

- [x] 新增 `DELETE /imports/{job_id}`，允许本人有写权限时删除纯暂存／跳过任务，支持版本检查。
- [x] 正式测量或已归档来源引用的任务返回明确 409；不删除已被引用的来源记录。
- [x] 原件清理延迟至事务结束后重查引用，上传与清理使用 SHA 锁保护共享原件和并发操作。
- [x] 新增专项测试已覆盖任务删除与原件保护，使用真实 MySQL 回滚夹具和临时原件目录。
- [x] 暂存任务删除入口、确认文案、pending删除200、刷新并回①上传已在两宽度浏览器通过；后端专项覆盖越权／旧版本。
- [x] 正式测量／归档来源任务409及共享原件引用／SHA锁保护由后端专项通过，前端依结果禁用危险入口；未清理生产个人任务。
- [ ] 暂存删除的越权／版本冲突／共享原件和正式任务保护逐项UI交互尚未穷尽。

### 9. 导入确认按科研流程重做

- [x] 样品已改为按编码／名称／批次搜索的选择器；执行及前测配对按所选样品显示名称选项，阶段使用中文。
- [x] 已移除重复的批量确认和第二步直接提交入口，保留逐文件单位／关联确认及正式测量提交确认。
- [x] 已增加测量编码冲突、多分块后编码超长的可操作错误，失败时整体回滚。
- [x] 截图已确认当前阻塞之一：提交汇总显示“阶段未选择”，随后报样品／阶段／阶段序号必填；不得把未知阶段自动猜成科研事实。
- [x] 核对候选仅预选唯一样品／单个执行且显示建议依据；下一步与③入口统一先校验，缺样品／阶段／序号在②按文件中文说明并聚焦，桌面／窄屏恢复提交200；原件归档不要求关联。无自动科研阶段／序号。
- [x] 第三轮2例及第二轮回归保留阶段／配对校验、重复原因、失败修改、原样重试与viewer403；不是穷尽所有阶段时序组合。
- [x] 真实浏览器完成上传 → 核对 → 提交 → 结果，并核对反馈在当前视口清楚可见。

### 10. RGA／XPS 原件归档与结构化解析分离

- [x] 未知／RGA／XPS 原件归档保存完整字节并核对 SHA-256，归档状态为待解析 `pending`。
- [x] 未经验证解析器的文件不创建测量点、仪器通道或光谱，不根据文件名伪造实验数值。
- [x] 独立原件归档无需样品关联；未知格式不建立未经确认的样品事实。
- [x] 导入专项验证：12 项新增测试、4 项解析进程测试、34 项既有导入回归通过；使用真实 MySQL 回滚及临时原件目录，未修改生产科研记录。
- [x] unknown／test.rga／最小Chart XML流程样本真实上传、独立原件归档、下载bytes与SHA逐一相等，sample=NULL、pending、测量／点增量0；第三轮另有uploads ZIP真实XPS Chart配置原件流程证据。
- [ ] 缺少真实RGA原始语料及含可信谱点的完整XPS仪器导出，待取得后验证对应原件与解析边界；不得把test.rga、最小XML或Chart配置称为真实RGA／完整XPS科学解析验收。
- [x] 操作手册明确支持的真实解析格式、待解析状态、归档和科学导入区别及后续处理方式。

### 共通要求与最终验收

- [x] 沿用现有工程目录和 ALE 视觉风格，未另建一套项目结构；本清单原位写入 `progress_log.md`。
- [x] 数据库仅使用新编号增量迁移，执行前备份并校验既有数据不丢失，迁移重跑核对通过。
- [x] API 静态契约、生成 Python／TypeScript 模型、前端类型与实际后端保持同步；新增设备、模板、归档、导入入口全部登记。
- [x] 最终review-workspace-build-final.log含vue-tsc／Vite通过（27.22秒）；本次只读重新核验review-workspace-dist-sha.log中41个生成文件与现有dist逐项SHA一致，index SHA256=c38f8c829a41fc25dddfc3d853686e65f820f95d11ca88debda7e1489e2fe9cb；main与canonical均1.5.0。旧dist资产保留。
- [x] 已列主流程、批次专项、导入定位与审查修复均启动真实MySQL／Uvicorn／Chromium并留截图；桌面1440与窄屏390的JS／宽度核查通过，具体日志分组列于下文。
- [x] 原位更新现有《功能实现与操作手册》：入口、按钮、逐字段说明、填写示例、点击效果、错误处理、权限、验证结果。
- [x] 原位更新《第一轮开发报告》的持续开发章节，记录真实根因、变更文件、数据库迁移、验证证据及未完成项，不新建重复报告。
- [x] 本次确认工具可见进程中无测试／服务／构建进程，5个白名单源码缓存无符号链接且全为.pyc，删除63文件共1,122,398字节，逐项复查不存在；完整路径和分项数量见本节末尾。未发生EPERM。
- [x] 最终实操验收：创建计划 → 下拉选择关联对象并创建执行 → 自定义步骤 → 绑定样品 → 管理暂存任务 → 归档尚不能解析的 RGA／XPS，每步均有清楚的成功／失败反馈。

### 最终证据核对与剩余验收（2026-10-16）

以上十项按「实现／已验收部分」与「尚缺的具体界面或真实环境」拆分，完成部分均已勾选。当前入口统计为71项已勾、8项未勾；全文含历史重复记录共110项已勾、9项未勾，历史Windows待办与当前入口重复，不作为新增未完成需求。当前状态为代码实现与已列范围自动化验证完成，以下两项环境／实操验收独立保留：

- [ ] Windows本机确认本项目PID，停止旧后端后运行根启动入口，核对当前1.6.0实际运行时和新路由、依赖安装与常驻服务；Linux同app的Uvicorn重启不代替本项。
- [ ] 用户使用自己的真实账户、正式数据逐步操作并确认结果；缺少的真实RGA／完整XPS语料及上方明确列出的专项UI边界按实际证据补验。

证据分组如下，历史运行、定向重跑、重试有重叠，不能把所有passed累加成一次完整测试总数。deselected为本组未选，不是skip；既有2项临时schema DDL skip仍保留。

| 证据／阶段 | 实际结果与边界 |
|---|---|
| phase5-browser-desktop-final／narrow-retry | 原主流程每宽度2例；命名创建、参数模板隔离、删除归档、原件和暂存管理 |
| 本session outputs/batch-archive-{desktop,narrow}-final.log | 每宽度2例；批次依赖、CAS重试、历史保留与角色隔离；非生产批次写入 |
| round5-import-readiness-{desktop,narrow}.log | 每宽度2例；②缺项中文文件提示、聚焦／滚动、保留输入及补齐后200 |
| round5-import-regression-phase3-{desktop,narrow}.log | 每宽度1例；真实ZIP Eoptics／XPS配置、原样重试、重复原因、测量管理／权限 |
| review-workspace-desktop-final／narrow.log | 每宽度3例；清空计划、绑定409／503恢复、归档标记／时间；共6例 |
| review-phase4-import-plan.log | 2例通过；旧phase4确认前定位断言已修复，计划联动与绑定回归通过；审查最终共8例，不另加早期单例重试 |
| phase5-regression-phase{2,3,4}.log | 旧流程分别2／2／5例；是历史分组，不称最终16例一次全跑 |
| 隐藏依赖专项（任务82／83） | 交接65项通过；源码及6个新增参数化回归已核对，未找到原始65项日志，未补造命令／耗时／单次运行记录 |
| review-workspace-build-final.log／review-workspace-dist-sha.log | 最终类型检查与构建通过；41生成文件本次独立SHA复核全相同，manifest SHA256=134c9af85e1b1208911633dc40586f4cca7fb46419774b2b0d0fd8a4038ced8f |

每个上述最终浏览器用例日志核对JS errors=[]、回滚后独立连接37表内容与17份生产原件SHA一致、临时原件删除。原件17份和既有7个任务／22个条目予以保留；此为测试日志及只读诊断证据，本次收尾未查库或写库。真实批次778的2条样品依赖已核实；权限受限依赖只显示统一保护提示，管理员可按可见范围看到完整计数。

精确缓存清理记录（本次实际执行，非引用旧轮）：

| 删除目录 | .pyc文件数 | 字节数 |
|---|---:|---:|
| H:\ALE_AI\backend\app\__pycache__ | 37 | 453860 |
| H:\ALE_AI\backend\app\parsers\__pycache__ | 4 | 66526 |
| H:\ALE_AI\backend\tests\__pycache__ | 19 | 467303 |
| H:\ALE_AI\database\__pycache__ | 2 | 41476 |
| H:\ALE_AI\api\models\python\__pycache__ | 1 | 93233 |
| 合计 | 63 | 1122398 |

删除前完整检查目录及祖先无符号链接、内部均为普通.pyc文件，工具可见范围无活动pytest／Uvicorn／Playwright／构建进程；删除后5目录均不存在。没有删除17份生产原件、备份、凭据、迁移、日志、dist或node_modules；未发生权限错误，无需删除授权工具。本次后续只进行文档／静态文件检查，不导入应用Python以免再生缓存。Windows宿主进程不在Linux进程可见范围，不据此声称Windows服务已停止。

手册1.7第40–47节及开发报告第五轮最终补录已原位对齐。后文各日期的“仍待补／并行中”是历史状态；已由后续证据解决的事项以本节及对应补录为准，Windows／真实语料等实际未完成项继续保留。

---

2026-10-15。第一轮开发范围：认证与用户、首页、批次、样品。不得导入历史 Excel 或修改原始实验文件。

数据库已执行 0001/0002 版本化迁移，备份在 backups/before_phase1_20261015T095243Z。问题关联九值约束一致；新增会话/邀请/应用设置、用户令牌版本和批次样品行版本。原有 23 表行数保留（迁移时均为空）。迁移记录含 SQL SHA256，重复执行跳过已应用版本。

Vue3/TS/Element Plus 前端与 FastAPI/SQLAlchemy/PyMySQL 后端已落盘。当前10项测试通过（含真实浏览器登录、批次创建、样品创建编辑、邀请生成、Cookie恢复），所有测试写入事务回滚。独立审查发现并已修正过期令牌退出、密码修改后会话、可空更新契约及问题统计枚举。

运行限制：Linux 工具结束后后台进程被清理，已尝试 detached subprocess 并确认下一调用不可达。因此无法宣称用户 Windows 的 localhost 服务已持续运行。已创建 start-workbench.ps1 和 启动工作台.cmd，Windows 本机运行后自动打开 http://127.0.0.1:8000/login；该启动脚本尚无法从当前工具执行，不能宣称 Windows 验证通过。生产前端由后端同源提供，不依赖 Node。首次在网页使用 backend/.setup-code 建立管理员，没有默认密码。

最终重建、契约核对、10项测试与截图重跑均完成；开发报告、启动说明已保存；最终检查原科研表及用户/会话/邀请/审计全部0行，只有app_settings1行及迁移记录2行。待本机双击验证持续服务启动。

2026-10-15 Windows 安装修复：用户 Python 3.14 下旧 PyYAML 回退源码编译失败。已更新兼容依赖并验证 Windows CPython 3.14 x64 全部预编译包可解析下载；启动脚本使用 binary-only 安装、成功 SHA256 标记及 pip check/导入检查，中断后再次双击自动重试。新版依赖在独立 Linux Python 3.10 环境 pip check 通过，9项真实 MySQL 后端测试与1项浏览器流程分别通过。启动说明和开发报告已更新。Windows 实际启动尚待本机确认。用户要求每个功能完成就启动网页展示，已逐项提供真实截图并解释持续启动限制。


2026-10-15 后续启动修复：读取 Windows server.stderr.log，确认 app/schemas.py 动态更新模型调用 Annotated.__class_getitem__ 导致 Python 3.14 AttributeError。改用 Pydantic FieldInfo.rebuild_annotation() 保留原字段约束及校验器。此前仅在 Python 3.10 跑测试的验证范围不足，本次已创建实际 Linux CPython 3.14.7 独立环境安装锁定依赖，9 项真实 MySQL 后端测试通过，另行启用的 1 项 Uvicorn/Playwright 完整流程通过，共 10 项；有 1 条第三方弃用提示。浏览器登录、批次样品创建编辑、用户邀请和会话恢复通过，测试写入回滚。Windows 启动仍需本机入口确认，未宣称 Windows 服务已启动。


2026-10-15 文档交付：新增 reports/功能实现与操作手册.md（1.0），核对实际前后端实现，覆盖所有本轮页面的入口、按钮、字段、默认值、权限、保存与报错效果、验证限制和更新记录。后续每次功能或影响操作的修复须同步更新本手册及变更记录；用户规则已保存。此次未改业务代码或数据库。


2026-10-15 UIUX集中优化完成：统一视觉tokens与PageHeading/FormSection/StatePanel，优化导航、首页、列表、抽屉分组固定footer、字段校验、防重复、未保存确认、关联跳转与错误重试。未改后端业务/API/DB结构，无新增生产依赖。最终build通过；原10项+新增7项分三批全部通过，日志在reports/ui-ux-20261015-final-*.log。五视口检查、43张新版截图、旧图基线和自包含前后对比HTML已保存。操作手册1.1、第一轮开发报告与设计规范更新。Windows常驻启动仍须本机入口确认。


2026-10-15 第二轮最终收尾（实际执行）：源API同步SampleTransition必需context_redacted bool及不可见运行六字段NULL；运行任意历史后process／全部steps／全部link任何PATCH返回409。重新打包、生成Python／TS／frontend contracts和Swagger预览，API72路径／123操作／131schema／55implemented；真实DB字段及29枚举校验通过。历史页裁剪显示“关联信息受权限保护”，阻止“无关联执行／未填写备注”误导；409显示准确历史不可改原因。vue-tsc／Vite build通过（16.78秒），dist逐文件字节一致同步且保留旧哈希。

后端原始最终日志phase2-final-backend.log保持71 passed／10 skipped（含37迁移、5并发）。本次契约同步回归22 passed（31.19秒，和71项重叠）。最终Linux CPython3.14.7／Playwright Chromium分组：desktop1440 1 passed／1 deselected（40.60秒），narrow390 1 passed／1 deselected（40.77秒），旧test_browser.py 1 passed（12.32秒），所有单次call<60秒；旧测试预期无需改动。两视口新增真实不可见运行裁剪UI验证通过，42张第二轮截图、JS0，真实API与MySQL测试外层回滚后独立连接确认无测试残留。日志均在reports/screenshots/phase2-final-{desktop,narrow,original,contract-regression,contract,build}.log。不累加为单次总通过。

只读迁移status再次验证0003／0004结构及checksum通过，迁移校验加固已记录；legacy in_process无活动load=0，未改状态／未补造历史。日志phase2-final-migration-status.log。原位更新功能手册1.3、开发报告、UI设计规范、API契约报告及相关api/docs，清除历史参数仍可改与browser待补说明。Windows持续启动仍未实际验证。

清理前确认空目录及源码缓存无运行依赖，最终已清理精确路径：

- `H:\ALE_AI\backend\pytest-cache-files-5fc9p0cc`
- `H:\ALE_AI\mysql_extract`
- `H:\ALE_AI\downloads`
- `H:\ALE_AI\backend\.pytest_cache`
- `H:\ALE_AI\backend\app\__pycache__`
- `H:\ALE_AI\backend\tests\__pycache__`
- `H:\ALE_AI\database\__pycache__`
- `H:\ALE_AI\api\tools\__pycache__`
- `H:\ALE_AI\api\models\python\__pycache__`

首次EPERM已按要求调用allow_cowork_file_delete（Windows路径未命中挂载，改项目挂载路径成功），白名单重试9项全部成功并确认不存在，最终无失败保留项。完整记录reports/screenshots/phase2-final-cleanup.log。未删dist旧哈希／备份／凭据／原实验／日志／运行env，frontend/.runtime候选未动。


2026-10-16 Phase3 独立解析器接口（实施中，供主代理接入）：`from app.parsers import parse_file; parse_file(content: bytes, filename: str) -> dict`。返回 JSON 兼容 `type/parser/version/status/blocks/warnings/blocking_issues/filename_hints/source`；status 为 parsed / needs_confirmation / original_only / rejected。blocks 每个 sheet/测量表头一块，含 metadata、points、statistics、warnings、blocking_issues、locator。points 使用 measurement_points 同名字段（decimal 一律字符串，整数 int；无效值 null），额外 raw_values（每列原值、单元格、data_type）及 locator；不含数据库 ID，不写 DB。metadata.instrument_summary 保留统计行；dispersion_params 保留内容模型参数，文件名 n/k 只在 filename_hints。统计基于所有有限厚度，包括已标异常点；sample SD(n-1) + population SD(n) 明示。精度超 DB 的原值不舍入，blocking_issues 阻止直接写入。unsupported 内容 blocks=[]、status=original_only，可保留原件预览，无虚假点。ZIP 批量上传本轮不支持，~$ 拒绝。当前只读四 ZIP 全部 XLSX SHA 去重为133份（含派生汇总），已发现20/23/29/38/41列 Eoptics 变体；XPS XML 是 Chart 配置（有轴单位但 Series 无光谱点），不可伪造 channels。最终覆盖计数与测试证据稍后追加。

2026-10-16 Phase3 独立解析器交付：已实际新增 backend/app/parsers/{__init__.py,core.py,requirements.txt} 和 backend/tests/test_parsers.py；未改其他业务/migrations/API/frontend/docs，也未导入 DB。`parse_file(bytes, filename)` 已按上段接口实施。四 ZIP 中133个唯一SHA非锁XLSX：130个 Eoptics、3个派生工作簿；130个测量块共987点，覆盖20/23/29/38/41列。逐SHA/文件名/点数/status证据及11项通过（含真实语料，9.184秒）在 reports/screenshots/phase3-parser-validation.log。异常点/重复号/缺失厚度/科学计数法/原始XML数值lexeme/超DB精度均保留；公式不求值、不用缓存冒充实测，summary原值保留不参与点统计。Tukey median-of-halves规则标记但纳入统计；sample/population均列明；派生统计写DB仍需显式精度转换确认。
XPS真实55个XML均是Chart配置，轴Binding Energy(eV)、Counts/s明确但无DataPoint/Point，因此original_only且blocks=[]，不输出虚假channels。55个VGD头均OLE CFB、含VGData/VGDataAxes等流，9个xls头OLE含Workbook流，未验证私有/BIFF数值编码，不支持结构化。RGA无真实文件，不造解析器。AOI/LBH表头未明确单位，raw保留且标准字段null、warnings提示人工确认，不猜度数。
主代理接入注意：decimal字段是精确字符串；issues在顶层和blocks两处，必须全部检查；needs_confirmation不允许直接写DB。original_only仍可预览原件，原bytes由主流程按source.sha256保存。解析器新依赖在 backend/app/parsers/requirements.txt（openpyxl==3.1.5、defusedxml==0.7.1），需主代理合并父requirements后才能在Windows启动中安装；本人按授权未改父依赖文件。独立测试使用PYTHONPATH=backend python backend/tests/test_parsers.py，设置ALE_PARSER_UPLOADS指向四ZIP目录可启用真实语料，不执行conftest的应用/DB加载。

2026-10-16 第三轮 backend/database/tests 实际交付（未改 frontend/、api/、docs/，未改旧 SQL）：

- 新增 backend/app/imports.py、original_storage.py、measurement_management.py；main.py 注册新路由并让运行时 OpenAPI 使用真实第三轮 schema；db.py 加启动反射迁移门槛。新增 database/migrations/0005_import_management.sql；migrate.py 新增完整结构后置验证，含类型/null/default/extra/generated、引擎/排序规则、索引顺序/唯一性、FK规则、CHECK精确表达式与ENFORCED；新表还核对完整列/索引/FK/check集合。旧0001–0004及基础SQL未修改。
- 0005 已实际执行，执行前备份 backups/before_migration_20261016T013814733344Z；保留全部既有行数。新增 import_jobs(owner_user_id,status,row_version)、import_items(job_id,filename,sha256,storage_key,parse_result,confirmation,status,result)、import_confirmations(job_id,confirmation_hash,result)、source_file_occurrences(owner,filename,sample,import_item唯一,source_file)。measurements 加 source_file_id/import_item_id/import_locator/provenance/row_version，唯一(import_item_id,import_locator)；measurement_points 加 raw_values JSON。--status 已再次验证0001–0005 checksum及0005实际结构。
- 新建 H:\ALE_AI\storage\originals（当前无文件）。所有真实写入前按 SHA 寻址：先写 bytes、flush/fsync、核验 hash，再以不覆盖已有对象的原子 link 建立不可变对象、读取再核验，然后 DB 引用。filename 不参与磁盘路径。测试使用 ALE_ORIGINALS_ROOT 临时目录并清理。DB失败不删除已持久化SHA对象，避免并发引用竞态；可能留下无引用的不可变对象，未实现自动GC。
- source_files 按全局 SHA 唯一去重，新的全局file_name仅存SHA，不存第一个owner的文件名；每次上传确认形成独立 occurrence，保留自己的文件名/notes/sample。预览不返回其他owner去重详情。job只允许owner访问（包括admin也必须是jobowner）；测量按既有sample scope，原件按可见occurrence或sample scope，既有admin全局样品权限保持一致。

精确前端接入接口（现有 envelope: code/message/data/request_id/timestamp，分页另有meta；所有接口Bearer鉴权）：

1. POST /api/v1/imports/preview，multipart唯一字段 files[]（可重复），1–20文件，各<=20MiB，总内容<=100MiB；解析multipart期间另有100MiB+256KiB请求流上限。拒绝路径文件名、控制字符、Windows盘符、Office锁文件。返回201 data={job_id,owner_user_id,status:'draft',row_version:1,created_at,items:[...]}。items含item_id/job_id/filename/sha256/parse_result完整parser返回/status/confirmation/result/created_at/suggestions，不返回storage_key。suggestions.samples含样品及batch、batch_hint_match、已绑定且有权限的processes、current baseline_measurements；optical_models为现有模型只读选项。全部仅建议，必须人工选择。
2. GET /api/v1/imports?page=1&size=20（size<=200），仅自己的job分页；GET /api/v1/imports/{job_id} 返回详情及完整items/points/metadata和最新候选。前端人工改关联保存在本地确认表单，提交confirm时保存confirmation snapshot，不另设草稿PATCH。
3. POST /api/v1/imports/{job_id}/confirm，JSON={expected_row_version:int>0,items:[{item_id:int>0,action:'import'|'original_only'|'skip',sample_id?:int,process_id?:int,stage?:enum,stage_seq?:uint,measurement_code?:str<=80,optical_model_id?:int,confirm_units:bool=false,confirm_associations:bool=false,confirm_duplicate:bool=false,duplicate_reason?:str<=4000,pair_measurement_id?:int,notes?:str<=10000}]}。items 1–20且ID不重复，未知字段422。import必须sample_id/stage/stage_seq/confirm_units=true/confirm_associations=true。stage为initial/after_o2_plasma/after_o3_pre/after_ale/after_hf_only/after_o3_only/intermediate/final/other；process若选必须已绑定sample；不创建工艺参数或transition，不改变样品状态/row_version。original_only可不选sample；若选sample仍须确认关联。skip只保存选择，不造source/measurement/dataset。
4. 确认返回 data={job_id,row_version,status:'draft'|'completed',pending_count,items:[{item_id,action,measurement_ids:[],warnings:[],source_file_id?}]}。每次只确认所选，未选择保留pending；完成选择后job版本+1，pending_count=0才completed；失败整次DB回滚，所有未成功选择仍pending。job锁+规范化全body hash（含expected_row_version）持久化响应；相同body重试回相同result，不同且旧version为409。已确认item只允许同content取原item结果，不能改成另一个动作或关联；同一job/item不可double写。前端成功后刷新job，新一轮用新version。
5. 文件所有block都会导入，每个block独立measurement，默认编码IMP-{job}-{item}，多block加-1/-2；用户编码多block也加后缀。parser顶层或任何block blocking_issues均拒绝import(422)，允许original_only。未知格式/XPS配置/VGD/RGA无可信parser只保留original，不创建dataset/channel/point。已测量SHA默认409，必须confirm_duplicate=true并提供非空duplicate_reason才新建独立measurement，绝不自动覆盖或supersede；同名不同SHA为本人范围warning。
6. pair_measurement_id必须同sample且current，initial不允许before baseline；模型不同明确返回warning并存confirmation/provenance；不擅造模型n/k事实，也不自动生成差值派生结果。原始metadata、parser/version、locator、filename_hints、完整统计、confirmation保存provenance及import snapshot。points保留raw_values/dispersion_params/outlier标记和单元格定位。统计按parser50位Decimal保留；不可精确放入旧DECIMAL列的汇总保持NULL并列入summary_not_exactly_representable，完整精度在provenance，绝不静默round。AOI/LBH无明确单位仍为NULL，原值保留。
7. GET /api/v1/measurements?page&size&sample_id&process_id&stage&current&quality（另兼容is_current/quality_flag），按scope分页；GET /measurements/{id} 含points/provenance；GET /measurements/{id}/points 返回全点。PATCH /measurements/{id} JSON={expected_row_version,quality_flag?:'ok'|'suspect'|'abnormal'|'excluded',quality_note?:string|null}，至少一质量字段，其余字段422，版本过期409。仅改质量与measurement row_version，不允许改科学数据。
8. POST /api/v1/measurements/{id}/supersede JSON={replacement_measurement_id,expected_row_version,expected_replacement_row_version,reason}。双方同sample、current、无冲突链；按plan->process->sample->measurement顺序锁定；原子设置旧is_current=false及reason，新supersedes=id，双方版本+1，保留历史并标记依赖derived_results无效；返回旧measurement完整详情及replacement。无自动替代入口。
9. GET /api/v1/source-files?page&size&sample_id；GET /source-files/{id}含仅可见occurrences；GET /source-files/{id}/content授权后读取实际原件并重新SHA核验，返回attachment下载（RFC5987中文名），缺失或损坏409。列表/详情不泄漏其他owner的文件名/来源/notes。
10. GET /api/v1/instrument-datasets?page&size&sample_id&process_id&instrument_type&sample_mapping_status；GET /instrument-datasets/{id}?include_channels=true&include_datapoints=true，只读已有数据，scope按sample或operator，空时返回空列表。没有虚构仪器写入接口。
11. 运行时 /openapi.json 提供全部新增接口及严格请求schema、multipart结构；/docs可查看。按本次禁止改API/docs的要求，静态api/openapi及文档目录不更新。本轮未重启Windows在运行服务；部署时需由既有启动流程安装新依赖并重启后使用新增接口。

验证结果：
- 新增 backend/tests/test_phase3_imports.py（51项）、test_phase3_concurrency.py（1项真实双连接等待job锁后回滚）、test_phase3_management.py（4项）、test_phase3_migration.py（36项通过，2项需显式开启临时schema DDL的测试跳过；遵守仅rollback未执行这两项DDL测试）。第三轮合跑92 passed/2 skipped，47.33秒。
- backend/phase2/parsers/migrations/管理回归78 passed/1 skipped，55.72秒；skip为未配置真实语料路径（原parser真实语料前轮已有独立验证，本轮不重复历史入库）。最后上传/并发/契约复查54 passed，47.76秒。存在一个既有Starlette anyio弃用warning，无业务测试失败。
- 真实multipart测试覆盖文件数、单文件/总尺寸、非法路径/锁文件/zip膨胀；真实MySQL rollback覆盖preview与完整points/raw/provenance、owner隔离、手工绑定、duplicates、版本重试、全rollback、哈希损坏下载/确认、original_only不造dataset。并发测试只使用未提交fixtures，第二事务阻塞直到第一事务rollback，随后404；不冒充已验证commit后的跨进程网络场景。
- 修复实测问题：audit action使用既有约束允许的insert；候选process查询避免自动关联导致SQLAlchemy编译失败；重复检测覆盖legacy point source关联；上传流上限在multipart spooling前生效。
- 父requirements锁定新增openpyxl==3.1.5、defusedxml==0.7.1、python-multipart==0.0.20；全部requirements以pip download --only-binary=:all: --platform win_amd64 --python-version 314 --implementation cp --abi cp314成功解析下载（Linux运行测试，未声称Windows服务已重启验收）。
- 验后实际DB import_jobs/import_items/import_confirmations/source_file_occurrences/measurements/measurement_points/source_files/instrument_datasets均0行，生产storage/originals 0文件；没有自动批量历史入库，没有残留测试原件。

2026-10-16 imports/store-worker 专项修复完成（仅本次负责范围）：
- backend/app/imports.py 的 existing_source 查询增加既有 measurement_management.measurement_scope(user)，measurement.source_file_id 与 legacy measurement_points.source_file_id 两条关联均先限定可见 measurement。全局 source_files SHA 唯一去重、排序锁定及个人 occurrence 仍保留；不可见 owner 的已测 SHA 不再触发 409、duplicate confirmation/reason 要求或 duplicate warning。管理员沿用既有 sample scope，不另改权限规则。
- 新增 backend/app/import_worker.py：模块顶层 spawn target，明确 multiprocessing.get_context('spawn')，不调用 shell。preview 以 await parse_preview 替换同步 parse_file；监督逻辑在线程执行，解析在独立进程，每服务进程跨请求/跨事件循环最多2个解析子进程，每文件20秒（从启动完成后 join 开始计时）。排队异步等待，不占用事件循环；超时 kill/join/close，崩溃/启动或结果读取异常返回明确 parser_timeout/parser_worker_failed blocking_issues 的 original_only 草稿，blocks=[]，不是无原因丢点。结果经临时文件传递避免大结果管道死锁，子进程回收后清理；请求取消仍等待监督清理后才释放并发名额。
- 上传20文件/20MiB单文件/100MiB总量/流式请求上限全部保留；Office ~$ 锁文件在 worker 前明确拒绝，worker 仍调用原 parse_file，未绕开解析器解压检查。未修改 parsers/core、original_storage、API、frontend、docs。原件 fsync/hash/不可覆盖寻址和读取授权实现保持原样，测试继续使用 ALE_ORIGINALS_ROOT 临时 store 与真实MySQL rollback。
- backend/tests/test_phase3_imports.py 新增6项：A/B同bytes，measurement/legacy-point来源，主动提供或不提供duplicate consent四组合均成功且无外owner warning；可见legacy-point仍409；失败草稿原件保留、科学import拒绝且整次回滚、original_only可确认、worker不可用时锁文件仍拒绝。新增 backend/tests/test_import_worker.py 4项真实spawn验证：超时kill/reap与事件循环响应、进程崩溃可读失败、5请求实际最多2进程重叠、重复取消后回收且归还2名额。
- 最终日志 reports/screenshots/phase3-final-import-tests.log：Linux CPython3.14，真实MySQL，分5组执行。imports 15 passed(29.64s)+23 passed(34.06s)+19 passed(48.15s)=57项；worker+第三轮management/migration/concurrency 45 passed/2 skipped(11.99s)，skip为需显式启用的临时schema DDL测试；backend/contract/phase2/phase2_concurrency回归34 passed(41.77s)。五组合计136 passed/2 skipped，非单次运行计数。既有Starlette anyio弃用warning，无测试失败。最初整批尝试因工具60秒时限未完成，未计入通过数。
- 最终独立连接确认 import_jobs/import_items/import_confirmations/source_file_occurrences/measurements/measurement_points/source_files/instrument_datasets 全部0行，生产 originals 0文件，证据附在同日志。Windows兼容性通过显式spawn及顶层target设计与Linux真实spawn验证；未声称已在Windows本机运行或重启服务。没有新增API模型字段、迁移或生成模型变动。



## 2026-10-16 Phase 3 parser 最终边界修复（独立无数据库验证）
- 仅修改 backend/app/parsers/core.py、backend/tests/test_parsers.py，保存 reports/screenshots/phase3-parser-final.log；未修改 imports/API/frontend/docs，未导入数据库。parse_file(content: bytes, filename: str) -> dict 签名保持，原输出字段保持；parser version=1.1.0，公式 raw 新增保真字段。
- worksheet 不再 ET.fromstring 全量建树。所有 ZIP XML/.rels 成员先 defusedxml.iterparse start/end 流式扫描并移除已处理元素，DTD/entity/external entity 禁用；所有成员（包括非 XML）实际解压累计计数且检查 ZIP 声明总量，均 <=100MiB；重复 ZIP 成员拒绝。预检完成后才 load_workbook/iter_rows，单元格真实 r 和 row r 必须明确、匹配、唯一递增，不信任 dimension。
- 准确限制：输入 <=25MiB；workbook 声明 sheet 数和实际 worksheet 数均 <=16；真实 XML 最大行 <=10000、列 <=256；整个 workbook 实际 XML cell 总数 <=100000，openpyxl 会补齐的各 sheet(max_row*max_col)累计 <=200000；全 workbook 候选 XML row（含表头/空行/摘要）累计 <=10000，这是在 openpyxl 前执行的保守 points 上限；实际输出 points 另累计 <=10000。缺 dimension、dimension 与实际 cell 最小/最大坐标不一致、或 row 超出 dimension 均严格阻断 original_only、blocks=[]。
- 输出 UTF-8 JSON <=16MiB；XML 预检还使用保守输出预算 sum(512+12*cell_text_UTF8_bytes)，共享字符串另加 max_shared_string_UTF8_bytes*引用数*12，超额可能提前拒绝；点/摘要/统计/issue 构造时增量预算，最终 JSONEncoder iterencode 再核实际结果大小，超限清空所有 partial blocks。XML 累计节点 <=1000000、深度 <=64、单个 text/tail/attribute <=8192 字符，共享字符串文本累计 <=32768 UTF-8 bytes。以上限制均为整个 workbook 范围，不能靠增加 sheet 绕过。
- 出现 layer_2/3/..._thickness（含未知单位）一律 unverified_multilayer，整份文件仅原件，不能只导入 layer_1。公式保存 formula、formula_attributes、cached_value_lexeme（不经 float）、cached_type、cache_present（区分无<v>与空<v>）；缓存包括 NaN/错误/字符串/非法数字均原样保留、始终 untrusted_formula 阻断，不计算、不当作可信测量值。预检发现的任何公式包括非测量列/前言均阻断。
- 最终无 DB 单独运行 test_parsers.py：23 tests 全通过、0 skip，19.701s。新增 regression 包括 undersized dimension 隐藏 row4、missing dimension + sparse row100005、真实坐标/列/错误 dimension、17 sheets、跨 sheet 实际 cell/grid/候选行预算、稀疏矩形、未验证多 layer、公式有/无/空/异常 cache、前言公式、共享字符串输出放大、实际解压/文本/节点/深度/输出限制；预检拦截测试 mock 断言未调用 openpyxl。
- 四个原始 ZIP 全量只读 SHA 去重语料：130 Eoptics、精确987 points，列型20/23/29/38/41；55 XPS配置XML、69其他原件。真实 workbook oracle reset_dimensions 全读独立计数，并与真实 XML 逐点对比所有数字 raw lexeme/typed fields/dispersion params/单元格定位，公式/缓存单独精确比对。128 Eoptics parsed，2 needs_confirmation：300nm/15.xlsx 与 15-40cyc- Pulse 20Kpa.xlsx（含公式，保留全部点和缓存但阻断）。本轮未触碰数据库、原件存储或部署服务；worker隔离由另一个任务处理。


## 2026-10-16 本轮文档原位收尾与源码缓存安全清理
- 已复核已有最终日志，原位更新`H:\ALE_AI\reports\功能实现与操作手册.md`1.4（第1／13／16／25–27／31节）、`H:\ALE_AI\reports\第一轮开发报告.md`第三轮及`H:\ALE_AI\启动说明.md`；本条为本轮记录，无新额外报告。未改代码／API／前端／启动脚本，未执行DB／迁移／业务测试、正式导入或重启服务。
- parser1.1.0最终23 tests通过、0 skip（19.701秒），四ZIP只读130 Eoptics／精确987点，128 parsed、2公式needs_confirmation（300nm/15.xlsx及15-40cyc- Pulse 20Kpa.xlsx）阻断科学导入。更新whole-workbook限制：16 sheets、实际最大row10000／col256、实际cells100000、补齐grid200000、候选XML rows10000／输出points另10000、JSON16MiB、所有成员实际解压100MiB；保守输出预算及XML复杂度限额详见手册26。dimension缺失／不符整份original_only，公式／缓存保真但始终不可信，多layer整份阻断。
- worker每服务进程最多2并发，20秒从子进程启动完成后join计时，超时kill/join/close，parser_timeout／parser_worker_failed保留原件original_only草稿、blocks=[]；仅可见测量同SHA重复要求确认，跨owner不可见不触发409／确认原因／warning，含legacy来源。后端最终五组15+23+19+45+34=136 passed／2 skipped，含concurrency，非单次运行；两skip为临时schema DDL未开启。证据`H:\ALE_AI\reports\screenshots\phase3-parser-final.log`及`H:\ALE_AI\reports\screenshots\phase3-final-import-tests.log`。日志未留完整shell调用／分组选择，未补造。
- 已确认无数据残留的历史证据为同后端最终日志末尾独立连接import_jobs/import_items/import_confirmations/source_file_occurrences/measurements/measurement_points/source_files/instrument_datasets全部0行、`H:\ALE_AI\storage\originals`生产0文件。本轮仅复核日志，未跑DB或清空原件，不将该历史状态冒称其他agent后续browser执行后的状态。
- browser最终正在其他agent跑，保持明确待补：手册1.4第31节“前端／browser最终”行、开发报告第三轮“最终补录区”，待该agent补桌面／窄屏、viewer、pending、原样重试、下载、质量／取代、截图／JS、最终build／dist及其rollback独立无残留证据。Windows本机安装／持续启动／目标网页及人工确认亦待补；根entry已按依赖hash自动补装，但健康旧服务可能仅reuse，必须确认本项目PID、停止旧后端再重启，不代称Windows验收。
- 安全清理前仅枚举源码范围、排除数据／依赖／运行目录；确认目录非symlink、内部仅pyc，并搜索源码和启动入口无运行路径依赖后，实际成功删除5项并确认不存在：`H:\ALE_AI\backend\app\__pycache__`（33文件373967字节）、`H:\ALE_AI\backend\app\parsers\__pycache__`（4文件66602字节）、`H:\ALE_AI\backend\tests\__pycache__`（22文件641473字节）、`H:\ALE_AI\database\__pycache__`（4文件84886字节）、`H:\ALE_AI\api\models\python\__pycache__`（1文件77055字节）。无.pytest_cache或空pytest-cache-files-*待删项；删除当时逐项确认不存在，但随后backend/database/api/frontend/src安全扫描已发现`H:\ALE_AI\backend\app\__pycache__`、`H:\ALE_AI\backend\app\parsers\__pycache__`、`H:\ALE_AI\api\models\python\__pycache__`三项再生且非空，具体生成进程未核定；保留新生缓存，避免反复追删干扰并行验证，其余两项该次复查未出现。无EPERM、无删除失败，故未触发allow_cowork_file_delete；不宣称最终缓存全空，后续测试仍可继续重生。
- 未触碰storage/originals任何文件、backup(s)、credentials、migrations、logs、runtime/.runtime、dist旧哈希、node_modules及原科研文件。确切清理路径与范围亦已记录现有开发报告第三轮末尾，无额外清理报告。
- 文档静态核对通过：两份报告最终通过数／状态／资源限额／公式缓存／worker错误字段及Windows说明存在，已移除解析／查重“仍在修复”的过期结论，代码围栏成对；本轮未运行应用测试／DB。缓存再生情况已修正到开发报告与本记录，保留browser最终待补。


## 2026-10-16 第三轮最终实际验收补录

本次在 Linux CPython 3.14 中运行真实 Uvicorn + Chromium，连接现有 MySQL，使用 SAVEPOINT 请求事务及外层 rollback；不是 Windows 启动验收。新增 `backend/tests/test_phase3_browser.py`，原件写入 pytest 临时 `test_store`，未执行正式历史 bulk。

- 桌面1440：1 passed / 1 deselected，pytest总时40.33秒，流程35.96秒；窄屏390：1 passed / 1 deselected，pytest总时37.25秒，流程32.19秒，均小于60秒。共2个浏览器用例通过，0失败、0跳过；deselected是每组排除另一宽度，不是skip。
- 每组从uploads ZIP直接读取两份真实Eoptics bytes（4点、81点），加真实XPS配置XML及unknown共4文件一次上传。预览测量增量0、全pending、全不勾选、阶段序号为空；人工样品/执行/stage=initial/stage_seq=0、单位/关联核验后，一次确认两份测量和一份original-only，另一份继续pending；reload后恢复继续original-only，不增加测量。有效异常点及每点raw_values逐项保真。
- 确认服务器完成后丢弃HTTP响应，点击“原样重试确认”返回相同结果、不增加测量。同SHA再次导入先409；勾选允许重复但原因空时前端拦截、不发请求，填原因后独立新增测量。结果共3测量、89点/每组，旧历史保留。
- 正式测量页实际读取detail/points，下载bytes SHA-256一致，保存质量备注、加载替代ID并确认supersede。将同一fixture owner降为viewer后，upload/质量操作禁用，浏览操作写请求0；主动越权confirm/PATCH各403。两宽度JS异常均0，7处截图检查body/document宽度均等于viewport。
- 14张最终截图为 `reports/screenshots/phase3-{1440,390}-{preview-pending,lost-response-retry,multi-confirm-results,measurement-detail,supersede-confirmation,viewer-imports,viewer-measurement}.png`。实际查看桌面detail、窄屏preview及supersede截图：无可见文字叠影/遮挡、卡片长文件名与SHA正常换行；窄屏表格在自身区域横向滚动，长批次页面较长。截图等待350ms组件过渡后重新生成；动画中间帧不作为最终视觉结论。
- parser/imports定向回归：57 imports分五组8+11+19+6+13全部通过，23 parser（含四ZIP只读语料）全部通过，0 skip。两项parser测试的XML正则修正为兼容 ` />`，否则测试构造未实际修改dimension；未改parser业务逻辑。日志保留最初2失败和修复后的23 tests OK，不把失败批次混入通过总数。此前136 passed/2 skipped全套未重跑，也不与本轮计数累加。本轮自动化功能回归为82通过（57+23+2），另有8个契约兼容用例通过。
- `npm run build`含vue-tsc通过，3218模块；dist最终36文件逐一SHA匹配，清理144历史过期产物。契约validate/gen_models通过：237引用、77路径、128端点、155 schemas，835 DB字段、147非DB字段、31枚举。仅补ParserRawValue的formula/formula_attributes/cached_value_lexeme/cached_type/cache_present五个可选字段，同步bundled/TS/Python/frontend contracts；8个实际parser输出JSON Schema与Pydantic往返通过，未改业务。
- 两次最终浏览器teardown通过全部33表内容指纹前后比较；各组4个临时原件清除，test_store不存在。全部回归结束后另建独立MySQL连接核对import_jobs/import_items/import_confirmations/source_file_occurrences/measurements/measurement_points/source_files/instrument_datasets均0，生产storage/originals=0文件。MySQL自增序号消耗属于rollback正常行为，不宣称其回退。
- 证据：`reports/phase3-final-browser-desktop.log`、`reports/phase3-final-browser-narrow.log`、`reports/phase3-final-build.log`、`reports/phase3-final-contract.log`、`reports/phase3-final-imports-regression.log`。browser命令在backend下设置ALE_BROWSER_TEST=1、LD_LIBRARY_PATH后，分别pytest tests/test_phase3_browser.py -k desktop/narrow -v -s；真实ZIP默认ROOT.parent/uploads，也可设ALE_PARSER_UPLOADS。parser独立命令为PYTHONPATH=. ALE_PARSER_UPLOADS=/sessions/intelligent-hopeful-fermat/mnt/uploads /tmp/ale-repair314/bin/python tests/test_parsers.py。

操作入口和字段沿用本手册：统一导入中心→多选原始文件→上传并预览→逐文件勾选“本次处理”并选动作；正式导入需手填样品ID、可选执行ID、阶段及阶段序号，点击“核验关联ID”，勾选单位与关联确认；“确认所选并提交”只处理当前所选。结果不确定时“原样重试确认”，未选择文件从任务列表“打开任务”继续。相同SHA需主动允许并填写原因。测量详情可下载、保存质量，取代需明确加载替代ID、填写原因、读取双方最新版本、勾选确认后保存。只读成员可查看与下载，不能写入。Windows本机持续启动及用户实际使用确认仍待本机执行。


## 2026-10-16 第四轮业务逻辑与交互修复（文档收尾）

- 本轮按业务方 8 项要求做前后端同步修复，真实连接 MySQL：计划删除/归档、批次内批量创建 1–50 片小样、从计划发起执行并继承步骤骨架（只映射 `plan_step_id`，不复制计划值）、绑定改为可搜索多选样品选择器（单条与批量）、通用化学体系（体系/物种/步骤模板）与执行级可选关联、步骤 `step_name`/`custom_parameters`、弹窗未保存修改保护、四步导入向导与就地反馈。迁移 `0006_general_chemistry.sql` 为可重复增量脚本并已并入 `schema_migrations`；API 契约 1.3.0 → 1.4.0（86 路径／142 操作／174 schemas／83 implemented）。
- 绑定故障的真实原因已定位并修复，而非隐藏报错：弹窗原先要求手填「样品 ID」，填错即由服务端 404 显示 `Resource not found`；批量绑定接口当时不存在。现由 `SamplePicker` 统一承担选择，并新增 `POST /processes/{id}/samples/batch`。连带修掉步骤请求体误带 `chemistry_system_id` 导致 422 的契约违规（化学体系属执行整体，`system_id` 为主键名）。
- 浏览器验收 `backend/tests/test_phase4_browser.py`：5 passed／83.01 秒，覆盖 20 片批量建样（仅一次 `POST batches/{id}/samples/batch → 201`）、同计划两次执行互不影响、4 片批量绑定、执行级化学体系并守住 422 回归、体系/物种/模板创建、四类弹窗丢弃保护、导入失败与成功就地可见；每例 `ROLLBACK VERIFIED: 36 tables and 12 production originals identical`，JS 错误 0。回归：第三轮 2 passed／73.93 秒、第二轮 2 passed／97.24 秒（两宽度 `BROWSER ERRORS: []`）、非浏览器回归 52 passed／9 skipped；`vue-tsc` 与 `vite build` 通过，dist 40 文件。日志 `reports/test-phase4-browser-20261016-1514.log`、`reports/test-phase3-browser-20261016-1516.log`、`reports/test-phase2-browser-20261016-1516-full.log`、`reports/test-regression-phase4-20261016-1442.log`。
- 文档：原位更新 `reports/功能实现与操作手册.md`（1.5，新增第 32–39 节与「第四轮最终实际验收补录」，更新第 1／16／17 节）与 `reports/第一轮开发报告.md`（第四轮章节），未新建重复报告；补齐契约文档 1.4.0：`api/docs/permissions.md`、`接口开发规范.md`、`模块接口说明.md`、`phase1-contract-changes.md`，并按 `backend/app/chemistry.py` 源码核对修正化学体系可见性与删除保护表述（未归属体系仅 admin 可见，被引用体系删除 409）。
- 安全清理：仅删除可再生的源码缓存 5 项目录（`api/models/python/__pycache__`、`backend/app/__pycache__`、`backend/app/parsers/__pycache__`、`backend/tests/__pycache__`、`database/__pycache__`，删除前确认内部仅 `.pyc`、非符号链接、无运行依赖），删除后复查已不存在；未发现 `.pytest_cache`、空 `pytest-cache-files-*`、`*.tmp/*.bak/*.orig` 等调试残留。未删除 `storage/originals` 科研原件（12 份）、`backups` 迁移前备份、凭据、迁移历史、日志、`backend/.runtime`、`frontend/dist`（40 文件，当前部署产物）或 `node_modules`。
- 未解决：Windows 本机启动与用户人工确认待本机执行；化学体系模板尚无「套用模板」入口；旧 O₃/HF/TMA 字段仍在执行/绑定表单显示（可空，未按体系裁剪）；导入第①步上传区无常驻入口；历史 Excel 批量入库、分析计算与图表不在范围内。


## 2026-10-16 第五轮后端集成核验清单（本次负责范围）
- [x] 仅新增 `database/migrations/0007_step_parameters_and_archive.sql`，未改已应用 SQL；扩展 `database/migrate.py` 的 checksum/replay/post-validation。执行前备份 `backups/before_migration_20261016T085118586312Z`，0007 已入迁移账本，`--status` 复查 0001–0007 全通过。
- [x] 0007：batches/processes.archived_at DATETIME NULL；两类 steps.parameter_snapshot JSON NULL；step_parameter_templates(template_id BIGINT UNSIGNED PK AUTO_INCREMENT, template_name VARCHAR128 NOT NULL, owner_user_id BIGINT UNSIGNED NOT NULL FK users RESTRICT/NO ACTION, definition JSON NOT NULL, row_version INT UNSIGNED DEFAULT1, created_at/updated_at)；audit CHECK增加step_parameter_template。未改写科学行/状态/原件。
- [x] 注册现有 step_templates.router；PlanStepCreate/Update、ProcessStepCreate/Update 复用 ParameterSnapshot 并保存独立 JSON 快照；模板修改/删除不改变已存步骤。新增 GET /api/v1/tools 分页 keyword 搜索，返回真实tool_id/tool_code/tool_name；POST /api/v1/processes/{id}/archive、/batches/{id}/archive 必传expected_row_version，返回详情，权限/行锁/CAS及旧版本409，幂等归档不重复bump，archived_at独立于log_status/status。
- [x] 删除保护按真实依赖类型与数量中文反馈，包括附件/问题关联，不执行级联删除；保留历史工艺PATCH冻结。创建计划/工艺引用错误含batch_id/plan_id/tool_id/chemistry_system_id中文字段，受限引用缺失与隐藏统一404。兼容既有化学体系PATCH缺失422行为。日志仅request_id/method/path/status，不记查询值、正文、令牌、异常文字；未处理异常也返回同request-ID响应头。
- [x] ale_app只读诊断：`WHERE batch_id=1 OR batch_code='1'` 唯一结果 batch_id=778,batch_code='1',status=active,row_version=2；批次总1条/min=max778。`WHERE plan_id=1 OR plan_code='1'`与`WHERE tool_id=1 OR tool_code='1'`均空；计划表/设备表各0行。因此截图的1是编号与主键混用，plan/tool ID1均无有效引用；没有为迁就输入造数据或改ID。
- [x] 新增 backend/tests/test_phase5_backend.py（最终18项）。真实MySQL SAVEPOINT+外层rollback覆盖模板快照独立、跨owner权限、archive历史与状态保留、CAS、依赖类型/数量、字段引用不泄漏、设备分页、日志脱敏/500 request-ID和0007精确结构；4项只读catalog替换验证column/FK/index/CHECK漂移拒绝，不在实库做漂移DDL。
- [x] 最终分组通过：backend/phase2/phase3_management/phase4=43 passed(69.40s)；phase3_migration/migrations/phase5_backend/模板unit/phase5_imports=103 passed+2 skipped(97.20s，后续增5项)；最终phase5_backend/模板unit/contract/phase2_concurrency=30 passed(34.79s)。分组有重叠，不累加为独立用例总数；两skip为既有临时schema DDL未显式开启。既有Starlette anyio弃用warning。最初大组超过工具时限不计通过数；旧断言兼容修正后上述组均通过。
- [x] 独立ale_app只读连接将迁移备份中34张业务/配置表原有列的全部行值逐项对比当前值，完全一致（仅排除两个迁移账本）；当前batches1/plans0/processes1/tools0/templates0/import_jobs7/measurements0/source_files1，均保留原值。production originals只读计数17文件，未操作。测试自增序列正常消耗，不承诺自增回退。
- [x] 历史集成交接已由后续browser及API1.5.0同步完成：模板CRUD、两归档POST、tools GET及快照／归档字段均已登记；该后端子任务当时未改frontend／API的范围说明保留为历史。Windows服务重启仍见顶部未完成项。


## 2026-10-16 第五轮真实浏览器与旧流程回归（browser 负责范围）
- [x] 新增 `backend/tests/test_phase5_browser.py`，真实 MySQL + Uvicorn + Chromium，桌面1440×1000两例通过（70.43秒，另2 deselected）、窄屏390×844两例通过（69.70秒，另2 deselected）。证据 `reports/phase5-browser-desktop-final.log`、`reports/phase5-browser-narrow-retry.log`；此前失败调试日志保留，不计通过数。
- [x] 命名批次选择创建计划201；计划发起执行时命名批次/计划/设备选择均显示编码名称并保存真实外键。执行创建表单无执行模式或手填关联ID，无旧O₃/HF/TMA专属字段；批量绑定同样无旧专属字段。真实发现并修复 `frontend/src/components/ExperimentWorkspace.vue` 的route query ID字符串问题：转Number后Element Plus已选项正确显示名称，不再停留“当前关联 #”。
- [x] 通用步骤默认源/脉冲/吹扫/等待/压差五组及独立温度，自增自由诊断组和任意字段/单位；通过UI另存模板，计划快照流量12.50，更新模板99.00后计划历史仍12.50；实际继承骨架全部值空，再从模板应用99.00并独立改33.00、温度180，保存后计划/模板/实际三者独立。两次真实Uvicorn stop/join旧线程、start新server并reload读取均保留快照；限制：同一Python app/同一未提交rollback连接，不是全新OS进程或Windows部署重启。
- [x] UI批量绑定增加2片，连创建时1片共3片；含步骤/绑定执行删除409且就地中文依赖反馈；归档200保留所有快照/绑定，reload后归档按钮消失；无依赖空执行实际DELETE204并确认行不存在。
- [x] unknown.bin、test.rga、XPS配置XML真实上传→仅原件确认：UI无样品/阶段控件；数据库source_files与occurrences样品均NULL、parse_status=pending；三份逐次浏览器下载与原始bytes及SHA256完全一致，measurements/points增量0。待处理任务从UI删除200、返回上传区且DB行不存在；Eoptics选样品但不填阶段/序号时，确认步骤就地显示文件名与“样品、阶段、阶段序号必填”，未建测量。
- [x] round5共20张截图 `reports/screenshots/phase5-{1440,390}-*.png`，全部检查body/document不超viewport；实际查看窄屏实际参数编辑、桌面通用模板、窄屏阶段反馈图，字段与反馈可见，参数长窗需垂直滚动。所有新旧浏览器用例JS errors=[]。
- [x] 必要兼容修改仅旧browser tests：phase4/phase3导入改命名样品/执行选择并走第3步提交；phase2改命名批次、通用参数快照，保留未知实际值、映射、装卸历史、重复执行与viewer权限断言。真实回归 `reports/phase5-regression-phase4.log` 5 passed/98.49秒；`reports/phase5-regression-phase3.log` 2 passed/98.56秒（单工作流44.00与41.61秒，仍<60）；`reports/phase5-regression-phase2.log` 2 passed/103.39秒。新旧共13个浏览器用例分组通过，无skip，非单次总跑。
- [x] 最新frontend/src复制到/tmp/bf，执行vue-tsc --noEmit与vite build通过并复制dist，41个生成文件逐项SHA一致；日志 `reports/phase5-browser-build.log`，仅已有大chunk提示。旧dist资产保留，未做无关清理。
- [x] 每用例外层rollback后独立连接比对全部37表内容指纹、17份生产原件SHA前后完全一致，临时originals目录删除。最终另建独立只读连接：batches1/plans0/processes1/tools0/templates0/import_jobs7/import_items22/measurements0/measurement_points0/source_files1，未清理原有个人任务/原件。自增序号正常消耗，不宣称回退。
- [x] batch archive 前端已由下方专项真实浏览器验证补齐（桌面/窄屏各2例）；Windows本机持续服务重启仍未执行。该项不代表Windows部署验收。


## 2026-10-16 批次归档 UI 专项验收
- [x] 修改范围：`frontend/src/views/RecordsView.vue`、`backend/tests/test_phase5_browser.py`、`backend/app/main.py`；另更新本清单、构建dist与截图/验证日志。未修改操作手册、开发报告、API契约或后端归档逻辑。FastAPI title=`ALE Workbench 1.5.0`、version=`1.5.0`，运行时OpenAPI版本断言通过。
- [x] 批次列表/详情提供owner operator与admin归档按钮；确认框说明保留样品/计划/执行/全部历史关联及业务状态；读取最新详情后提交expected_row_version。成功、归档失败与依赖删除失败均常驻页面面板，详情打开时同样可见；eligible错误提供归档快捷按钮。archived_at驱动列表/详情独立已归档标记与详情归档时间，不改status。
- [x] 复用round5真实MySQL/Uvicorn/Chromium与SAVEPOINT/外层rollback：桌面1440×1000 `2 passed, 6 deselected / 45.11s`；窄屏390×844 `2 passed, 6 deselected / 44.46s`，共4例通过、0 skip；未重跑其他6例。命令：backend下ALE_BROWSER_TEST=1、LD_LIBRARY_PATH=/tmp/libs2/usr/lib/x86_64-linux-gnu，python3 -m pytest tests/test_phase5_browser.py -k 'batch_archive and desktop'（或narrow）-v -s --tb=short。日志在本session outputs `batch-archive-desktop-final.log` / `batch-archive-narrow-final.log`。
- [x] 实测admin非owner DELETE409显示样品7/计划1且>3.2秒仍可见；取消归档未写；确认前并发PATCH使旧版本POST409，失败面板持续可见；快捷重试重新读版本后POST200，成功>3.2秒仍可见。样品完整响应、计划本身/步骤/关联批次ID保持一致（计划响应嵌入最新批次元信息会反映归档）；业务状态仍active；列表/详情独立badge、reload后仍归档且入口消失。
- [x] owner operator详情归档200；同owner降为viewer后未归档记录无按钮、浏览0写请求，主动归档403；其他operator详情404、无归档按钮，主动归档404。两宽度JS errors=[]。
- [x] 12张截图 `reports/screenshots/phase5-{1440,390}-batch-{delete-dependencies,archive-cas-feedback,archive-success,archived-detail-reload,owner-archive,viewer-readonly}.png`；每张body/document宽度等于viewport。实际查看390依赖反馈、1440成功、390详情reload，文字/快捷按钮/双状态标记可见，详情内容垂直滚动。
- [x] 每例独立连接验证37表内容指纹与17份生产原件SHA前后完全相同，临时originals目录移除；自增序列正常消耗不承诺回退。最终独立ale_app只读诊断真实批次batch_code='1'/batch_id=778：status=active,row_version=2,archived_at=NULL；直接依赖samples=2，experiment_plans/processes/instrument_datasets/source_files/attachments/issues_links/optical_models各0。未对该批次执行任何写操作。最终37表内容聚合SHA256=`b583a97a74cda03f3ab0bc373129e739f25921d17f1ed95e78ae8b77fa464b09`；17原件manifest SHA256=`be5eb06dabf39a4d20852d67e18373040af382e2593ea77482a1ba2403bc8d7c`。
- [x] 最新src复制/tmp/bf后直接node运行vue-tsc --noEmit及vite build通过（npm脚本首次因复制依赖无.bin未启动编译；已改用相同工具JS入口成功）；41个生成文件复制dist逐项SHA匹配，旧资产保留。生成文件manifest SHA256=`3a2e6372e8dc86fdf9f46babe8d382a46b14b1f5828c76a086400f79c3680606`；index.html SHA256=`327c22a4fbf1f54ace8e75690143cab6f7b7cb84d12397e7abde1cd416fbfcc3`。outputs `batch-archive-build.log` / `batch-archive-diagnostic-sha.log`保留完整构建与逐文件SHA证据。
- [ ] Windows本机持续服务重启未执行，本次为Linux验证环境；不据此勾选Windows部署验收。


## 2026-10-16 第五轮第9项：进入确认前逐文件必填校验

- [x] ImportsView.vue统一下一步及顶部③入口；缺样品、阶段、序号／格式、单位与关联确认时留在②，按文件名中文提示、首字段实际聚焦与滚动，错误可点击重新定位，保留选择／备注。未选项不校验；original_only／skip无关联要求。阶段序号增加中文解释，不生成科学阶段或假定完整历史后建议序号。
- [x] phase5新增test_phase5_import_before_confirm_readiness_and_recovery两宽度用例，并更新已有required_stage用例符合新交互；当前phase5共10例（原8+新2）。命令均在backend，ALE_BROWSER_TEST=1 LD_LIBRARY_PATH=/tmp/libs2/usr/lib/x86_64-linux-gnu python3 -m pytest tests/test_phase5_browser.py -k 'import and desktop'（或narrow）-v -s --tb=short。桌面2 passed/8 deselected，51.39秒；窄屏2 passed/8 deselected，48.82秒。
- [x] tests/test_phase3_browser.py -k desktop/narrow -v -s --tb=short，同环境各1 passed/1 deselected，50.96／50.24秒。未改旧测试；不确定响应原样重试、重复原因／独立测量、下载及权限回归通过。每例37表及17生产原件SHA保持一致、JS0、临时原件删除，生产原件与科研行未改。
- [x] 最新src在/tmp/bf通过vue-tsc --noEmit及Vite build，41生成文件复制dist并逐项SHA匹配。manifest SHA256=0e76ed8825b0275bc5af1987996514887c3321f34a5677f8078c2e87880b7d5d；index.html SHA256=cecfca68ecaf3b58db678f29062302cd6c23676ad89a9d48ff0b651e98a08f4e。证据reports/round5-import-readiness-{desktop,narrow,build,sha}.log、round5-import-regression-phase3-{desktop,narrow}.log。已原位更新手册44节与报告第9项。未做API／迁移或安全清理。
- [x] 历史交接待办已由后续review-phase4-import-plan.log解决：旧phase4用例改为②定位断言并验证补齐后200；当时“尚未修改”的范围保留为历史，不再列作当前未完成。其余用例按各自日志分组记载。


## 2026-10-16 第五轮审查修复：清空计划、绑定冲突恢复与执行归档标记
- [x] ExperimentWorkspace.vue：新建执行清空计划时，确认「重建步骤」会清除继承实际步骤、计划映射选项及继承提示；取消恢复原计划和草稿。新建独立步骤提交plan_id=NULL、plan_step_id=NULL，真实POST201并详情重读通过。
- [x] 批量绑定409提供专用「刷新执行详情并保留输入」。GET成功后才解除冲突锁，移除已绑定ID、保留剩余选择与全部公共属性；GET失败保留冲突锁及输入。真实并发绑定导致409、一次模拟GET503、随后真实GET200和仅剩余ID重试POST201均通过。顺带修复公共完整ALE循环数以字符串提交导致422，现校验0–4294967295整数并以数值提交。
- [x] 执行列表／详情独立由archived_at显示「已归档」，详情持久显示精确归档时间和原日志状态；toast消失、Uvicorn stop/join/start及reload后仍存在，log_status=partial未改。同app／同回滚连接重启，不代表新OS进程或Windows部署。
- [x] 新增精确用例（各desktop/narrow）：test_phase5_clear_plan_discards_inherited_drafts_before_creation、test_phase5_binding_conflict_refresh_reconciles_and_retries、test_phase5_process_archived_badge_time_persist_independent_log。tests/test_phase5_browser.py目前16个参数化用例；本次定向6例通过，其余10例未在本次重跑。desktop 3 passed/13 deselected，45.05s；narrow 3 passed/13 deselected，44.06s。日志reports/review-workspace-desktop-final.log与review-workspace-narrow.log。最初循环数字符串422失败日志review-bind-recovery-desktop.log保留，未计通过。
- [x] 修正旧test_phase4_browser.py::test_p4_import_feedback_stays_in_view：缺样品／阶段／序号留在②、中文文件名错误、首控件聚焦且在视口内、无③submit／confirm POST／测量写入；补齐后进入③正式确认200。与test_p4_plan_run_inheritance_and_multi_bind定向合跑2 passed/3 deselected，53.38s，reports/review-phase4-import-plan.log。先前末尾旧phase4待修条目已由本次解决，其余3例本次未跑。
- [x] 全部上述8个最终用例JS errors=[]；每例独立连接比较37表指纹与17份生产原件SHA完全一致，临时原件删除。未修改后端业务、数据库迁移或生产记录。截图phase5-{1440,390}-{clear-plan-created-independent,binding-conflict-reconciled,binding-conflict-retry-saved,process-archive-badge-reloaded}.png，另重生成相关phase4截图；所有宽度检查通过，实际查看390绑定恢复／归档reload，字段、保留内容与归档标记可见。
- [x] 最终最新src通过vue-tsc --noEmit及Vite build，41生成文件复制现有frontend/dist并逐项SHA一致；旧dist资产／日志／截图保留，未执行清理。构建reports/review-workspace-build-final.log，SHA报告reports/review-workspace-dist-sha.log。


## 2026-10-17 AI 审查修复（已完成开发与已列范围验证）
- 已核对0009六表；采用ai_requests.result内部_server JSON保存预留槽、派发日期、意图和工具计划，不变更迁移。以下为最终修复及分组验证结果，早期开发中状态已由本检查点替代。
- 【历史，已由当前第2项及手册53节替代】当时崩溃pending继续保留预留与忙锁；现在过期可恢复，未知计费仍不自动退款或重试。

- 安全专项真实MySQL回滚12例通过（round6-ai-review-security.log）：不带ID追问、当前数据刷新、无历史模型文本、证据有效重放不重扣、所有权变化隐藏、外发前session撤销/过期/配置/角色/证据变化、端点清除旧key、精确pending槽及派发日期。每例43表与17生产原件一致；后续浏览器、构建及回归结果见下方最终分组记录。

- [x] 安全多轮完成：ai_requests.result._server内部JSON保存最近成功意图/工具计划，最多参考最近2轮各1000字符及4个去重计划；每轮重新执行当前scope工具，从不发送历史模型回答，客户端history额外字段仍拒绝。没有新建项目/报告或新增/修改迁移。
- [x] 每次模型发现/测试/chat外发及最终交付检查当前auth_sessions撤销/到期、users状态/token版本、配置revision与chat启用；此前所有工具证据重读hash一致才允许外发/交付。current_user增加内部_session_id供校验，未改变公开用户结构。
- [x] base_url变化未附新key时清除旧key；端点不变可保留。不同地址/路径均采取保守清除策略，未放宽同origin跨路径保留。
- [x] 已完成chat原ID查询只读重验session/config/证据；有效返回原答案与来源，replayed=true且无新外发/计费；失效或旧版无证据隐藏。UI成功重放仍为completed；真实浏览器验证服务端已完成后丢失响应，原ID取回且provider调用数不增加。
- [x] 新pending槽按max_tool_rounds+1（test/models=1）持久化；派发前写UTC日期调用数，daily按实际派发日期+pending未用槽计算，跨日不漏算；跨月停止后续外发。未知计费仍保守结算、不自动退款/重试。旧格式pending无历史配置，仍保守chat=5槽；旧已结算行没有派发日期，只能沿用created_at归日，无法追溯纠正旧账。
- [x] 分组完整结果（有重叠不相加）：round6-ai-review-core.log 27 passed/40.23s；security.log 12 passed/44.82s；tools-final.log 32 passed/43.75s（30工具+2交付撤权）；daily.log 1 passed（扩展日期结算断言）；auth-regression.log 9 passed/25.88s。完整test_ai大组因工具60秒时限中止，不计通过；最终按分组覆盖全部41个AI用例及30工具用例。早期unit失败为开发中日志，未作为验收。
- [x] 浏览器context.log 2 passed/39.49s（1440/390，第二轮context=none与无历史模型文本）；admin.log 3 passed/53.55s；replay.log 1 passed/27.04s（与admin中的pending用例重叠，新增已结算丢响应重放断言）。JS errors=[]。AI单测及浏览器fixture每例独立核对43表与17份生产原件，回滚后一致；无科研提交或原件变更。Provider仅MockTransport+固定公共DNS，未调用真实服务商或使用真实key。
- [x] round6-ai-review-contract.log：OpenAPI/902字段/32 CHECK、102 implemented路由、168 Python模型、请求/响应正反例、0008/0009只读结构验证通过；同步bundled/生成Python和TS/frontend contracts；vue-tsc/Vite生产build通过，生成dist逐文件字节一致。既有Pydantic、Starlette和WebSocket弃用警告及大chunk提示保留。四份API文档与手册51节原位更正，无新报告。
- 【历史待办，恢复已实现，见当前第2项；真实竞争仍待验】当时限制：崩溃pending永久保留预留与会话busy锁、无自动恢复/解锁API；需要后续设计可核对供应商账单的人工恢复方案，不擅自退款或重试。daily统计目前遍历AI请求账本，规模很大时需后续优化索引/聚合。Windows持续服务重启与真实供应商验收仍未执行。

- [x] 独立只读安全复核：未确认新的Critical/High阻断问题，支持作为模拟服务验证交付；未把顺序预留测试称为多进程竞争验证，未把跨日定点测试称为实际跨午夜运行。
- [x] 最终人工查看桌面管理员设置与390px追问截图；回答中攻击样例按普通文字显示，未执行HTML。截图为测试记录与模拟回答，不代表真实模型或生产科研记录。
- [ ] 真实多进程并发、崩溃恢复、实际跨午夜竞争、真实Provider TLS/工具协议/usage与Windows密钥ACL仍待专项验证。

## 2026-10-17 AI官方协议兼容修复（本地验证完成，真实DeepSeek待验）

2026-10-17 官方协议修复：初始当前记录及追问预查均为 `role=user` 的 `<UNTRUSTED_DATABASE_EXCERPT>` JSON 数据消息，含 `current_context`／`prior_plan_reexecuted` 来源及工具名/参数；角括号转义后JSON解码仍保真，数据库文本不能伪造外层分隔符。仅服务器system指令具有权威性；数据内指令、角色文字及旧用户意图不是指令或独立证据。首批消息无伪造assistant/tool；只有本轮服务商实际返回并校验的assistant.tool_calls才回填tool_call_id结果。预查继续执行当前scope查询、来源追踪和证据hash，外发/交付/重放继续重验；旧模型答案不外发。无成功当前查询时仍要求工具，模型直接答复以lookup_required隐藏，拒绝工具结果不能充当成功证据。

官方主机 `api.deepseek.com`（含/v1、/beta路径及主机大小写）必须显式 `provider_options={"thinking":{"type":"disabled"}}`，按主机匹配，不按服务商名称或模型ID猜测。配置PUT缺失时422；既有空配置GET仍可读取，test/chat在预算预留和网络前409阻止，底层completion另有防线；models发现可继续。前端输入该地址或读取旧配置后自动勾选并锁定“显式关闭 thinking”，显示官方默认thinking开启及本助手非思考工具流程的说明；需点击保存，才写入服务端。其他服务商保持其原配置，可自行取消参数。仍采用无成功预查时tool_choice=required、有证据后auto；显式关闭thinking解决官方required限制，未改用其他API或硬编码模型。

本轮最终证据（均位于reports，按最终分组计，不重复累计）：`round6-ai-protocol-core.log` 32 passed/40.62s，`revocation.log` 9 passed/35.97s，`followup.log` 7 passed/29.12s，合计全部48个AI用例（原41+新增7）；`tools.log` 30 passed/35.91s。拒绝型MockTransport记录真正发出的assistant消息，旧current_context/prior_0人工调用及孤立tool均返回400；测试包含有初始上下文、实际服务商多工具轮、真实scope拒绝他人记录和成功读取本人记录，3调用/330 Token，追问刷新数据且无旧模型文本；保留预算、轮数、字节、撤权及幂等回归。`browser-settings.log` 2 passed/23.45s、`browser-context.log` 2 passed/44.23s，1440/390两宽度JS errors=[]；设置保存及reload后锁定，切换其他端点可取消，无provider调用。各AI数据库/浏览器fixture独立核对43表和17生产原件不变。工具回归用SAVEPOINT+外层rollback，无正式科研提交；自增序列正常消耗不宣称回退。

`round6-ai-protocol-contract.log`契约/902数据库字段/32枚举约束通过，bundled及生成TS/Python/frontend contracts同步；`parity.log` 102已实现路由、168模型、11正例/34反例及5正/5反结果通过，包含DeepSeek配置跨字段校验，0008/0009只读结构核验通过。契约校验调用30秒工具超时后日志已记录完整PASS；生成步骤随后单独执行成功。`build.log` vue-tsc及Vite构建通过（Vite 28.81s），44个生成文件复制dist并逐一SHA一致，旧资产保留。既有弃用警告与大chunk提示保留。`unit.log`/`targeted.log`为开发中分隔符测试失败，已由最终core通过替代；`security.log`整组接近55秒被中止不计通过，改拆revocation/followup后全通过。未把部分运行计成完成。

仅本地MockTransport协议约束模拟通过，不能证明真实DeepSeek接受请求、TLS、模型行为、usage或账单。未使用真实Key，未外发科研数据，未执行Windows命令或重启旧服务；已知Windows旧1.2无AI的状态沿用此前记录，本轮未重新探测。真实Provider验收、Windows1.6持续运行/ACL、多进程并发与崩溃恢复仍待专项；【历史，恢复现已实现，见手册53节】当时pending保守预留/忙锁限制不变。未新建/修改迁移，未自动修改实际AI配置，未清理生产原件。


## 2026-10-17 后端恢复阶段记录（历史60项，当前以顶部108项及手册1.9为准）

- 已在 backend/app/ai.py 复用 result._server 增加固定120秒执行检查期限（非包含DB等待的硬端到端上限）、180秒恢复租期、派发前/响应后心跳、执行令牌 fencing、逐调用派发与已知用量检查点；复用 config 单例行锁和原六表，无0010，0009未改，运行版本仍1.6.0。
- 过期请求自动转 failed/request_recovered，释放会话 busy 和未使用预留；已派发未知费用按每次上限保守入账，绝不自动重派或退还未知费用。status/chat（reserve）/usage/requests/recover访问触发，无后台任务。旧格式pending保守等待300秒，按已有派发标记处理。
- 新接口：GET /api/v1/ai/requests（最近100，普通用户仅本人，管理员全局）；GET /api/v1/ai/requests/{request_id}；POST /api/v1/ai/recover（admin）；POST /api/v1/ai/requests/{request_id}/reconcile（admin，原因+供应商证据+实际tokens/cost+reconciliation_id，终态未知费用仅对账一次，原估算/证据/操作者完整保留）。无科研写入。
- HTTP适配器增加单次25秒绝对socket截止（含TLS/慢头/慢块），DNS最长等待5秒；下次调用前必须留足25秒；120秒之外结果不交付。HTTP前再次校验执行令牌和期限。
- 已分组回归：恢复专项9通过；上下文11通过；轮间撤权6通过；协议/配置23通过；服务8通过（共57个test_ai用例）；工具30通过。日志在当前session outputs/ai-recovery-*.log。真实MySQL恢复专项包括两个独立连接锁竞争（1205证据）、HTTP返回前恢复/迟到worker隔离；每次增强夹具回滚核对43表和当前16生产原件一致。此前记录17与当前基线差异未归因，未操作原件，不能冒称本次17。工具组使用其原有回滚fixture。待最后补充status触发/令牌伪造与chat未知费用边界后追加结果。
- 最后补充结果：status访问恢复+伪造执行令牌拒绝、chat未知费用仅计已派发一次共2通过（ai-recovery-boundaries.log）；真实httpx/httpcore默认传输路径使用假socket验证慢响应剩余25→1秒且超时停止，1通过（ai-recovery-socket.log）。当前test_ai共60项分组通过，test_ai_tools30项通过，共90项唯一用例。仅已有Starlette/Pydantic弃用/字段属性warnings；未接真实Key/供应商。未完成Windows正式重启与真实供应商验收，也未改API契约/UI。


## 2026-10-17 正式文档收尾补录

本次仅文档及日志归档，无代码／迁移／科研数据变更。恢复后端60项历史基线由最新108项分组覆盖，工具30、浏览器9另列；最新契约--no-db实际通过，DB最后超时不记成功。原件元数据当前16／2369146字节、17分片目录／76为空，缺历史逐文件manifest，差异仍待查。详见顶部六项和手册1.9第53–55节；不把历史17写成最新保护数量，不把锁竞争写成实际提交结算竞争。


2026-10-17 HIGH启动器收尾：仅修改start-workbench.ps1及既有启动说明／手册／进度／开发报告。共享项目venv、app.main和健康版本不能证明加载项目，legacy拒绝自动停止与复用；可信旧构建仍可升级。实际验证为tree-sitter解析、源条件派生Python模拟26场景、9静态保护及旧指纹重启分支检查；Windows实测待验，无服务停止／启动、DB请求或原件删除。

本次授权缓存清理实际结果：以目录fd和O_NOFOLLOW逐层打开项目路径及目标父目录，删除前仅接受普通.pyc、不跟随symlink；仅删除backend/app/__pycache__（46文件699445字节）、backend/app/parsers/__pycache__（2文件23559字节）、backend/tests/__pycache__（18文件552865字节），合计66文件1275869字节。三目录删除后及最终静态验证后均确认不存在；未发生Operation not permitted／权限错误，无需调用删除授权工具。其他缓存、运行日志、备份、依赖和所有生产原件均未清理。


### 第七轮 A/D 操作分工（2026-10-19）

- 负责范围：AISettingsView.vue、RecordsView.vue、ai.py 模型结果密钥脱敏、ai_provider.py 模型可选元数据；未修改恢复/对账、AppShell/router/研究助手或共享契约，未迁移数据库。
- AI：DeepSeek 官方预设 https://api.deepseek.com；其他兼容提供者保留高级输入。操作顺序为选服务商、保存 Key、发现、选模型并保存、同意通用测试、最后启用；测试无需先启用。显示发现/测试/启用禁用原因及密钥已存标记；更换端点清除旧密钥由后端现有绑定规则保障。
- 元数据来自实际 GET /models 字段白名单：id/name/owned_by/context_window/max_output_tokens/input_modalities/output_modalities/effort/api_capabilities.anthropic_messages.system_prompt_update；缺省显示未知，无硬编码模型或能力推断。只在本页本次发现展示可选字段，不新增持久字段。官方文档核对 https://api-docs.deepseek.com/api/list-models （2026-10-19）。
- 样品首页并列单个/批量入口；无需预筛批次，弹窗选择批次和可选母片、数量/前缀/起始序号/共同属性；复用现有 1–50 片可编辑表格与原子批次 API。完善批量页面离开保护、批次选项异步竞态和空批次禁用提交。
- 验证：test_phase7operations.py 9 passed；test_phase7operations_browser.py 3 passed（1440/390 AI，20 片编辑并提交）；0 JS errors。全部 AI 使用明确模拟密钥与 MockTransport，无真实外网模型调用或科研数据发送。样品测试夹具实际基线 11，创建 20 后外层回滚。43 张表和 5 个生产原件每次指纹一致。
- 证据：reports/phase7-operations-backend.log、phase7-operations-browser.log；reports/screenshots/phase7-operations-ai-synthetic-1440.png、phase7-operations-ai-synthetic-390.png、phase7-operations-bulk20-synthetic.png。
- 集成提示：GET /ai/models 的 models[] 现在除 id 外返回上述可选受限字段，请主代理同步契约。Vite 隔离构建通过；全局类型检查曾被 ProcessGridGroup.vue 两处未标注参数 v（TS7006）阻塞，此文件属其他分工，请主代理最终复核。未将隔离构建产物覆盖正式 dist。


### 第七轮：通用流程网格与嵌套组（2026-10-19）

- 入口：实验计划或实验执行 → 查看详情 →「编辑流程网格」。步骤为列、参数为行；「添加步骤列」「复制列」「左移／右移」「移除列」管理步骤。「添加参数行」为当前组各列增加自定义字段；每格分别维护值与单位，改变单位不会自动换算数值，空值存 NULL。源、脉冲、吹扫、等待、压差、温度、流量均可调整；分类自由输入，不强制 O₂/O₃/HF/TMA。
- 「添加嵌套组」创建组，在列标题选择「移入分组」；组名称与重复次数分别填写，可继续添加子组。明确流程顺序列出同层组与步骤的次序，组上移／下移调整顺序。总循环数与组重复次数留空均表示未知；不计算或推断实际次数。最多 32 组、4 层嵌套、500 个流程节点、每个快照 256 字段且 64 KiB、整次网格 1 MiB；重复数 0–1000000。
- 列标题「参数结构 / 模板」展开既有参数组编辑器，可以增加／删除参数组与字段，选择已存模板应用副本，或填写名称「另存为模板」。模板使用既有 /step-parameter-templates 接口，持久保存在 MySQL，所有权和版本规则继续生效。
- 「保存流程与参数」一次提交流程树及所有步骤快照，父版本冲突显示错误并保留输入。已有步骤 ID 原位更新；旧 planned_parameters、custom_parameters、实际物理字段和 plan_step_id 不被清除。已关联样品历史的执行不能覆盖；已映射计划的流程结构和循环语义受保护。
- 架构：experiment_plans/processes.process_flow 仅存流程树与步骤 ID，科学参数仍在既有 experiment_plan_steps/process_steps.parameter_snapshot；没有重复的组参数事实源。原有逐步接口会同步新增／删除流程引用，已分组步骤改序必须使用网格。
- 计划发起执行继续清空实际数值；有流程树时继承结构与映射，但总循环数和组重复次数全部清空为未知。实际流程必须独立记录。历史化学示例保留；化学体系页工艺模板的分类亦可自由输入。
- 迁移 0010_generic_process_flow.sql 由原执行器应用，未修改 0001–0009 SQL。新增两列 JSON 并把两张步骤表 step_kind 扩展到 VARCHAR(128)，去除原固定分类 CHECK。执行器支持恢复 DROP CHECK，识别 0010 后的历史版本检查，并验证 0010 实际结构。备份 before_migration_20261019T023533433145Z；逐字段验证原有 106 行科学／业务记录保持原值，状态复查通过。
- 验证：round7-process-regression.log 42 passed；round7-process-expanded.log 110 passed、2 skipped（两个既有可选测试）；round7-process-final.log 最终 6 passed，包含真实 MySQL、Chromium 操作／保存／刷新、µs 单位、自由分类、复制列、双层组、未知循环、模板持久化、权限/CAS、来源 ID 保留、失败事务回滚、通用化学体系。浏览器无 JS 错误，43 张表与 5 个生产原件指纹回滚一致。round7-process-build.log 为完整 vue-tsc/Vite 构建通过；在 /tmp/phase7verify/frontend 的本地依赖环境构建后复制 dist 至正式目录，避免挂载盘依赖读取超时。截图 reports/screenshots/round7-process-grid-{editor,reloaded,mobile}.png。


### 2026-10-19 最终故障恢复复核补记

独立复核发现并修复了向导首次创建后矩阵PUT失败丢草稿、创建响应丢失后重复记录以及旧格式计划继承遗漏参数结构三个问题。首次保存父记录成功、矩阵失败时保留原网格与未保存状态，重试使用原父记录。计划／执行创建按一次创建意图固定编码和请求，后端在同一事务写入audit_log指纹回执；相同请求返回当前原记录，不同内容或其他用户不能冒领。批量样品响应不确定时按原编码组查询核对，结果无法确认时保留待核对状态，不再次创建。离开前请记下界面显示的待核对编码；未保存的内存草稿不承诺跨刷新保留。

旧格式计划通过与现有编辑器一致的字段／单位映射生成空值实际步骤，保留名称、单位、计划映射和自定义参数结构；不复制计划数值或推算循环。运行期workflow两个POST现已采用严格canonical操作定义，先前generic限制已解除，历史描述仅代表修复前。

实际复验：round8-final-workflow-recovery-complete.log为9 passed；round8-final-p1-shared-browser-retry.log为7 passed，覆盖1500／390恢复、丢响应复用创建身份、矩阵503及样品核对；round8-final-p1-contract.log为2 passed。各次数据库用例回滚后43张表和5份生产原件指纹一致。首次shared-browser有5项因未配置ALE_TEST_FRONTEND而setup error，补齐配置后重跑通过，原日志保留，不计通过。

最新生产构建来自已完成vue-tsc和Vite的wizard-p1-build，逐文件确认当前源码和构建输入一致后同步到共享frontend/dist，并用共享构建复跑上述7项浏览器测试。旧可重建assets暂保留，未清理原件或业务文件。最新index SHA256为a74ba150e1f4f73b7d6fdef2d344e25cc50c6b616c7682dacfd63580c72e9c32；依据round8-final-p1-build-consistency.log。早期build-consistency与SHA只属于其历史快照，不再代表当前版本。Windows服务重启、跨进程实机验收及live DeepSeek继续待验。


补记：验证期间观察到生产库已有用户通过界面创建的 Admin/test 账户及 S04 批次、样品、计划、执行记录（2026-10-20 下午）。本轮测试均使用独立 ale_workbench_test，没有修改这些生产记录。


## 2026-10-20 Codex 接手：核心体验增量修复（A–E）

### 审查与安全边界

- 实际目录 H:\ALE_AI；未发现项目 CLAUDE.md / AGENTS.md，使用用户提供的 H 盘规范。核对 progress_log、产品重整方案、操作手册、开发报告、三账户报告、双向关联方案、OpenAPI、基础表和 0001–0013 迁移及真实实现。历史报告的清理授权不作为本轮授权。
- 生产库 ale_workbench：3 账户（management/research/testing 各一），18 样品；测试用途账户仍在生产库，不能视为隔离环境。独立 ale_workbench_test 在接手时为 0 账户、0 样品，13 迁移齐全。本轮不运行 setup_test_env.py、不初始化 Git、不执行迁移、不清理业务数据。
- 写入测试显式设置 ALE_DB_NAME=ale_workbench_test、ALE_REQUIRE_TEST_DB=1、ALE_ENVIRONMENT=testing、ALE_ORIGINALS_ROOT 指向 storage-test 或 pytest 临时 originals；现有外层 rollback / SAVEPOINT 保留。浏览器另核对 43 表与正式原件；正式基线见 reports/codex-core-repair/safety-before.json，复核见 safety-after.json。两份正式原件仅只读 SHA/解析，各 4 点，没有复制入测试库，没有 AI 或原始科研数据外发。

### A：批次、样品短编号、执行业务编号

- 修改 backend/app/{records.py,schemas.py,experiments.py}；frontend/src/views/{ExperimentWizardView.vue,RecordsView.vue}、components/{QuickBatchCreate.vue,ExperimentWorkspace.vue}、experiments/sampleCodes.ts；契约 domain.yaml。
- 向导在“参与样品”就地创建沉积批次，自动选中；取消保留数量/前缀。批次不冒充母片。编号默认 S01-1…S01-16，预览可逐行改，查询包括已归档/作废编号，下一次推荐未占用值。复用原原子批量 API、全局 UNIQUE 与批次锁；并发冲突仍由数据库拒绝。不能提前保证其他账户私有编号一定未被占用，冲突时保留输入，不泄露对方记录。
- 批量创建成功直接绑定本次执行。可选 request_key 复用 audit_log 保存创建指纹及样品 ID 回执；丢响应重试恢复同一意图，不按短编号猜测归属；不同内容复用键返回 409。无新表/迁移。
- 执行复用已有 process_code，默认短日期/随机后缀，可在执行详情“修改执行编号”修改；稳定 process_id/FK 保持。纯编号修改留字段审计并支持版本检查，已有历史时工艺参数继续禁止覆盖。已有样品改号/审计保留。
- 实际命令（backend）：.venv-win\Scripts\python.exe -m pytest tests/test_codex_core_repair.py tests/test_sample_experiment_links.py -q。改前执行改号复现 422：A-reproduction.log；阶段 A 6 passed：A-tests.log；最终回执/编号/权限/循环等见 E-final-affected-tests2.log（18 passed，包含下述 B/C/D 受影响验证）。

### B：导入表单减法与建议审核

- 修改 backend/app/imports.py、frontend/src/views/ImportsView.vue、frontend/src/imports/model.ts；契约 imports.yaml。
- 流程为“上传 → 审查关联建议 → 确认保存”，结果原位显示。默认已选可信文件、紧凑测点/均值摘要，需审查样品与阶段；执行可空。样品详情入口带 sample_id；执行上下文只在真实绑定选项可见时保留。
- 文件数字匹配小样尾号，不再匹配批次的第一个数字。数字匹配只是候选，不自动确认为事实；强编号/明确页面上下文可预填，最终提交仍明确审核。单位/关联确认集中在最终可见说明与按钮；服务端仍要求确认。阶段不猜测。
- stage_seq 留空在样品锁下自动分配，属于技术序号、不证明工艺顺序。模型、真实测量时间、明确前测、重复原因在高级核查。真实测量时间未知留空，不能使用文件上传时间替代；有时区时间按 UTC 保存。
- 同次上传可手选另一单块“初始”文件为前测，后端在一次事务中先建前测再关联；不按文件名自动配对。SHA、点级原值、质量标记、去重与回执保留。新可选字段缺省时不改变旧确认请求指纹。格式不可信仍可只归档。
- 默认不渲染/请求图表；校验错误也不再隐式启动隐藏图表。逐文件缺项可定位修复。实测桌面两文件审查页面约 1338px，窄屏约 1554px（1000px 测试视口）；截图与浏览器日志记录精确值。
- BCD-tests.log：新增专项 8 passed；E-backend-final.log：相关回归 92 passed、2 skipped；E-required-fields-retest.log：4 passed（旧 stage_seq 必填断言已按本轮需求移除，自动分配有新测试）。最终新增真实时间与回执测试见 E-final-affected-tests2.log。

### C：独立绘图与差值校验分开

- 修改 frontend/src/views/AnalysisView.vue；复用原 scientificanalysis.calculate 和 ScientificPlot。没有删除任何模型/配对校验。
- 独立/并列计算本来支持不同模型；修复页面差值 422 时一起清空原始图的体验：差值拒绝原因单列，重新取独立统计与原始图。不同/未知模型不输出可靠差值或 EPC。
- 深链接可带样品、执行、单测量；原始图不补坐标、不插值。既有分析 Δd=后−前；样品页“表观减薄量”=前−后，二者名称和符号含义分开明确，未改变旧分析 API 方向。

### D：样品详情直接复盘

- 新增 backend/app/sample_review.py、frontend/src/components/SampleResearchReview.vue；增量修改 records.py、participation.py、RecordsView.vue，契约 SampleDetail/SampleExperiment。
- 默认先显示短编号/批次/材料/状态/标称厚度、逐次实验及实际温度/流量、逐片循环与装卸节点，再显示所有测量（含被重测取代记录）、质量/MSE/模型、原图和原件入口、明确配对的结果。空属性和内部 ID 收入可展开技术详情。
- 仅采用导入中明确确认的同样品前测关联，不按时期、文件名或相邻测量推断；复用现有计算函数核对模型/阶段/真实坐标等。摘要要求两次 current、quality=ok、无异常点；异常或排除时解释原因，详细选择请到原科研分析入口。
- 表观减薄=前均值−后均值，正值减薄、负值增厚。只有测量时间确实包围同一实际执行、区间内无其他/时间未知执行、该片实际循环>0 时才除以逐片循环；设备总循环、累计两段循环不能代替。模型/时间/循环/质量不可靠均显示“无法计算：原因”，不填 0。展示计算版本、规则、来源版本/SHA/点指纹，不宣称验证 ALE 或机制。
- E-final-affected-tests2.log 覆盖 500 设备循环但该片 100 循环时结果 0.01 nm/cycle，负值表观增厚、未知时间/循环、其他执行、重测、异常点、跨模型和权限隔离。

### E：构建与回归、已知限制

- Windows 现有 backend/.venv-win 可用；系统默认 Python 缺依赖。为验证安装 playwright/openapi-spec-validator，安装 Windows 原生 Rollup/esbuild 可选二进制；未改产品 package.json/requirements.txt，未新增产品依赖。python-dotenv 保持原锁定 1.1.1。
- 前端命令（frontend）：node node_modules/vue-tsc/bin/vue-tsc.js --noEmit；node node_modules/vite/bin/vite.js build --outDir ../reports/codex-core-repair/frontend/dist。E-typecheck-delivery.log、E-build-delivery.log；通过，只有既有大 chunk 提示。
- 契约命令（根目录）：backend\.venv-win\Scripts\python.exe api/tools/validate_contract.py --no-db；api/tools/gen_models.py。E-contract-final.log / E-genmodels-final.log；静态校验及模型生成通过，未把 --no-db 写成生产数据库字段全量核验。
- 其他组 E-contract-concurrency-regression.log 为 14 passed、1 既有失败：test_archive_is_idempotent_and_delete_is_blocked_by_runs 的旧断言期望归档计划可删，现行生命周期保护返回 409；历史报告已记录，未改删除规则。
- 92 项回归中的 2 skipped 因旧 Linux 会话的 4/81 点原始附件目录在本机未挂载；另以当前本机两份 4 点正式原件只读解析通过（E-production-parser-readonly.json），不冒称旧 81 点附件已复验。
- 本轮数值结果限“椭偏表观变化”；历史缺失时间、循环、模型或配对不会自动补写。手动分析中单独保存的自定义排除方案仍通过原科研分析记录查看，不自动替换此默认摘要。
- 原服务未被本轮停止或重启；最终正式实例启动/跨进程重启、本人科研账户对真实数据的操作验收仍需按启动说明确认。新增原件导入只在测试库验收，不向生产写样例。
- 源码恢复点 reports/codex-core-repair/before；精确变更清单与补丁见 changes.json / source-changes.patch。imports.yaml 的原版本通过本轮确定编辑的逆操作恢复为对照；其余原有修改文件为编辑前副本。


### Codex 本轮最终交付检查点（2026-10-20，Windows 本机）

- 最终受影响组：E-final-affected-tests2.log，18 passed；账户用途与 research/testing 双向端到端：E-account-purpose-isolation.log，48 passed（离线 Provider，不发送科研数据）。相关较宽回归 E-backend-final.log 为 92 passed、2 skipped；这些分组有重叠，不能相加当独立覆盖数。
- 浏览器：E-browser-verified.log 为 4 passed / 44.26s；E-browser-confirmed-result-context.log 为 1 passed / 13.89s，合计分组 5 例。桌面 1440、窄屏 390，真实 Windows Chromium / MySQL。创建16片、下一组17起、修改数量使旧预览失效、取消保留输入、丢响应按回执恢复、两文件一次提交、跨模型差值拒绝后保留原始图、独立单片/批量内联批次均通过。最后增量的执行上下文保留分支在第5例覆盖：重新选择候选仍保留合法执行。
- 第5例也实测有历史执行改号 RUN-100-A 后样品历史同步显示；明确同模型、真实时间区间、逐片100循环、设备500循环，界面显示 11→10 nm、表观减薄1 nm、0.01 nm/cycle。截图 D-confirmed-apparent-summary.png 为隔离合成数据，不能当正式科研结论。
- 新增截图 A-wizard-short-codes-{1440,390}.png、A-standalone-single-bulk.png、B-import-compact-review-{1440,390}.png、B-import-saved-{1440,390}.png、C-cross-model-original-plots.png、D-sample-research-history-{1440,390}.png、D-sample-results-{1440,390}.png。已实际检查代表性桌面/窄屏、模型差异图和有依据结果图；页面无横向溢出，详情表格在自身范围内横向滚动。
- 最终类型检查与构建：E-typecheck-delivery.log、E-build-delivery.log，通过；最新构建依赖图56文件已同步 frontend/dist，逐文件SHA匹配，见 deployment.json / build-files.json。保留原有未引用静态资产，覆盖前文件副本在 before/deployed-dist；未停止/重启生产服务。
- 最终生产指纹：safety-after.json 与 safety-before.json 完全一致，43表、2原件。测试库业务写入均回滚。没有改迁移历史、正式记录、原件、有效备份或管理员/服务商凭据。
- 本轮判断：可在重新启动并确认加载本次构建后开始个人实验记录、导入和复盘的受控使用；正式实例跨进程重启持久化与本人代表性研究数据操作仍未执行。缺失的时间/模型/逐片循环或前后归属仍不能自动得到可信 EPC；已保留明确的无法计算原因。旧归档删除断言与未挂载81点附件不算已解决。


## 2026-10-21 启动依赖冲突修复

- 用户截图启动失败于 start-workbench.ps1 的 pip check：上轮安装 openapi-spec-validator 0.9.0 带入 pydantic-settings 2.16.0，要求 python-dotenv>=1.2.2，与正式锁定1.1.1冲突。上轮恢复dotenv后未跑全环境pip check，是开发验证遗漏；不绕过启动保护。
- 最小修复：将可选工具的 pydantic-settings 降至实际核实兼容的2.12.0（要求dotenv>=0.21.0），保留正式requirements全部版本。新增 api/tools/requirements-validation.txt，为可选校验器固定版本并引用正式requirements作为约束；backend/README.md补充安装命令，防止以后无约束升级。
- 实际命令：backend/.venv-win/Scripts/python.exe -m pip install --only-binary=:all: -r api/tools/requirements-validation.txt；pip check；启动脚本同一import probe。随后再执行启动器的 pip install --upgrade --only-binary=:all: -r backend/requirements.txt，重跑pip check通过（No broken requirements found.）。静态契约 validate_contract.py --no-db通过，bundled文件SHA未改变。
- 日志：reports/startup-dependency-repair/{compatibility-preflight,install,pip-check,import-probe,launcher-requirements-reinstall,pip-check-after-reinstall,contract-validation}.log；版本与结果result.json。未启动/停止生产服务，未修改数据库、原件或业务逻辑。可以重新从原启动工作台.cmd启动；未把依赖检查通过冒称整台生产服务已重启验收。


## 2026-10-21：批次冲突与样品科研履历增量修复

- S01/S02 实际仍为 active、未归档且未作废，各有8个样品；S01另有2条正式测量。全局 uk_batches_code 与按账户可见列表不同，造成不可见记录撞号时只显示通用冲突。未更改任何生产记录或唯一索引。
- 新建批次表单 / 向导可检查编号：仅对可见记录提供打开已有批次及生命周期恢复 / 安全清理预览；完全无关联的误建记录可更正编号，保留内部身份、状态并记录原因。有关联批次禁止更改编号；私有冲突不返回其他账户身份。正式 / 测试应用账户仍共用编号空间，测试建议 TEST- 前缀。
- 样品详情与既有样品历史页复用科研履历，展示独立执行、逐片循环、装卸节点、执行参数、测量、膜厚、图 / 原件入口。实验详情可进入样品完整履历。原始事件日志折叠保留。
- 累计和每循环表观结果新增实际参与依据要求：先装载后取出，或该样品已装载并记录已发生的执行时间；只有绑定或未来时间不算发生。循环缺失、作废执行不累计，不代入设备总循环。
- 隔离测试库 ale_workbench_test：最终后端67项通过，Chromium桌面1440及窄屏390共3项通过；生命周期、research/testing双向权限、重复两次执行、五片分节点取出、双向跳转均覆盖。类型检查、构建、静态契约及pip check通过。59份构建依赖文件同步并核对SHA256；43张生产表和2份原件指纹前后一致。未重启生产服务，需按原启动方式加载后端源码。
- 完整分阶段文件、命令、结果和日志：reports/batch-history-repair/README.md；恢复点before/，changes.json与source-changes.patch；最终日志backend-delivery.log、browser-release.log、contract-delivery.log、typecheck-release.log、build-release.log、deployment.log、safety-verification.log。历史缺失事实不自动回填；窄屏既有全站长会话顶栏拥挤未扩大范围重构。

## 2026-10-21 核心产品规范对齐：阶段一

- 已将本次用户规范整理为 reports/核心产品规范.md，并通过项目 AGENTS.md 设为持续开发约束。未找到项目 CLAUDE.md；以真实代码、现有产品重整方案和进度恢复现状，不声称继承聊天记忆。
- 已有：一计划多执行、重复用样、分节点取出、样品履历、显式导入配对及原件溯源。缺口：跨体系累计、实验侧逐片结果汇总和默认技术字段过多。
- 最小计划：先复用 participation/sample_review 将结果接入既有执行与计划详情；累计按显式体系及模式分组，未知体系逐次保留；再收起底层详情，将必要配对移到普通导入核对区，不新增页面、业务表或导航。
- 修改 backend/app/participation.py、backend/app/experiments.py；新增 tests/test_core_product_alignment.py。独立 ale_workbench_test，命令 .venv-win/Scripts/python.exe -m pytest tests/test_core_product_alignment.py -q --tb=short：先复现2项失败，再2项通过，日志 reports/core-product-alignment/{reproduction,backend-first}.log。生产只读43表2原件基线已保存。
- 阶段二正在验证：结果优先展示、测量详情与原件折叠保留、中文研究标题、双向跳转及导入上下文。尚未将隔离测试写成生产账户验收。

## 2026-10-21 核心产品规范对齐：阶段二

- 实验计划与执行详情复用 sample_review 的确定性结果；按执行、样品展示原始前后均值、逐片循环、表观变化、质量及图/来源入口。样品履历显示中文研究标题，累计按已确认体系和处理模式分组，未知体系逐次保留。
- 结果摘要、测量详情、原件三级展示；新增可用膜厚点计数（有膜厚且未标异常），不改写原始均值。必要前测配对移出高级核查；文件名阶段提示只能人工采用，确认提交前不写科学事实。
- 测量页用样品选择器和可搜索实验名称/执行编号替换普通 ID 筛选；关联名称在权限投影后解析。按技术 ID 定位、质量修订和替代测量进入可选折叠区，保护规则保留。同步实际使用的 frontend/src/contracts.d.ts 与共享生成契约。
- 主要文件：backend/app/{experiments,participation,sample_review,measurement_management}.py；frontend/src/components/{ExperimentResults,CycleSummary,ExperimentWorkspace,SampleExperimentHistory,SampleResearchReview}.vue；views/{ImportsView,MeasurementsView,SampleHistoryView}.vue；API既有schema及生成模型。没有新增路由或业务表。
- 后端扩大组98 passed、3 skipped（backend-final.log）；最终受影响组16 passed（backend-delivery.log）；新增名称检索/标签与解析分析组31 passed、3 skipped（affected-final.log），分组有重叠不相加。三项跳过均是外部真实ZIP/旧上传归档未挂载，四点和81点临时Excel已实测入库、完整下载及SHA一致。
- node vue-tsc --noEmit与Vite构建通过，typecheck-accepted.log / build-accepted.log；validate_contract.py --no-db及gen_models.py通过，contract-delivery.log / models-delivery.log。日志位于reports/core-product-alignment。最终浏览器和生产只读指纹待收尾；未把静态契约校验写成生产数据库全量验证。


## 2026-10-21 核心产品规范对齐：阶段三交付

本轮验收：后端扩大98通过3跳过；最终受影响16通过；解析 / 四点与81点 / 名称组31通过3跳过；浏览器新旧7通过。各组重叠不相加。3项跳过为外部真实归档未挂载；临时Excel原件字节及SHA完整性实测通过。类型检查、构建、静态契约通过，61份依赖构建文件同步；生产43表2原件指纹一致。服务未重启，需从原启动方式加载新后端。

完整分阶段文件、命令、测试与边界见 reports/core-product-alignment/README.md；恢复点before/，精确changes.json及source-changes.patch，最终日志backend-final.log、backend-delivery.log、affected-final.log、browser-final.log、typecheck-accepted.log、build-accepted.log、contract-delivery.log、deployment.log和safety-verification.log。旧数据缺失事实和跨多执行区间的表观结果不自动推断；本轮不新增全站导航改造。

## 2026-10-21：可视化与轻新拟物阶段0（等待视觉评审）

- 阅读用户附件与真实代码；只做三个局部预览，不授权附件中的后续全站推广。既有海军蓝/青绿、科研口径及功能保持；无依赖安装，无生产组件、路由、全局样式、后端、契约、数据库与原件修改。
- 新增 frontend/ui-review.html、vite.review.config.ts、src/ui-review/{main.ts,Review.vue,fixture.ts,review.css}。独立本机5178服务，无API代理/认证；build仅输出reports/soft-ui-preview/build，未覆盖frontend/dist。
- 原貌直接复用ExperimentResults、SampleExperimentHistory、SampleResearchReview、ScientificPlot；冷色/暖色轻拟物提供实验摘要表、样品时间轴、可展开图控件三个真实Vue样板。明确标注演示夹具，未挂载正式记录与原件。推荐冷色；零新增组件库。
- 预览 http://127.0.0.1:5178/ui-review.html；离线并排对照 reports/soft-ui-preview/对照预览.html；截图existing/soft/warm-{summary,history,chart,1440,390}.png；PNG/JSON导出证据。
- 实际命令：frontend下node node_modules/vue-tsc/bin/vue-tsc.js --noEmit、node node_modules/vite/bin/vite.js build --config vite.review.config.ts；根目录backend/.venv-win/Scripts/python.exe reports/soft-ui-preview/check_preview.py。类型与独立构建通过；浏览器三主题/1440与390/数据一致/缺值/导出/展开/Esc/键盘/reduced-motion通过，无pageerror、API或写入HTTP请求。日志同目录typecheck.log、build.log、browser.log、browser-results.json。初次检查脚本用系统GBK读取UTF8导出失败，明确encoding=utf-8后重跑通过；不是产品失败。
- 边界：独立构建有>500kB单包提示，未部署；没有生产数据库测试或指纹前后比较、真实原件/81点验收、用户操作计时。现有图默认模型合组暂保留，可展开选择来源。未把视觉样板描述为正式功能验收。
- 审计证据、组件库取舍、验证范围、回退与待确认项统一追加 reports/产品重整方案.md 的“现有可视化与轻新拟物·阶段0评审”；没有新建重复开发报告。等待用户确认视觉路线后再推广。

- 补充：离线对照页6图加载、暖色切换及390px布局检查通过，comparison.log / comparison-1440.png；已请求在Codex侧栏打开交互预览，返回queued。

## 2026-10-21 正式前端升级 P0
- 已接入正式AnalysisView/ScientificPlot：实验→样品→阶段、少点摘要表、来源分组、冷色图主题、折叠专业控件、既有导出。无后端/API/科学公式改动，无依赖安装，新增LabMetric。
- 类型检查、P0构建通过；baseline与P0正式路由1440/390截图/API链路通过。首次边界测试遇到新版Element Plus标签重复，改为combobox角色定位后重跑，结果见p0-boundaries.log。正式43表2原件只读基线已保存。

### P1 样品履历
- SampleExperimentHistory正式接入ElTimeline，服务器执行顺序、逐片循环/装卸、阶段测量/原件链接独立保留；条件及完整步骤按需展开。SampleResearchReview改为真实均值/质量/MSE读数卡，缺项不补。未改变RecordsView/SampleHistoryView的数据加载或权限。
- P1类型检查与构建通过，1440/390正式路由截图和测试日志reports/ui-upgrade/p1-*；最终回归结果在本轮后续检查点记录。继续P2逐片结果表。

### P2 逐片结果与P3首页
- ExperimentResults改为逐执行、逐样品对照表，直读research_review的服务器前/后均值、表观减薄/EPC或拒绝原因；原始测量和计算依据按片展开，原件和科研履历直接可达。没有复制计算公式。
- P2类型检查、构建通过；测试日志及前后截图reports/ui-upgrade/p2/。P1边界重跑已通过，跨模型返回422后保留8个原始点。P3仅压缩首页说明并精炼按钮/真实记录卡/统计样式，继续使用现有dashboard接口。

### P3/P4与扩大验证
- P3正式首页构建与1440/390截图链路通过（p3-browser.log）。P4冷色Token由lab-ui.css统一，复用原PageHeading/FormSection/StatePanel，只新增实际复用的LabMetric，未创建一套按钮/卡片包装框架。补充AI悬浮入口对选择器、表格、科研图的避让。
- P4第一轮4项浏览器通过：原件4点、真实API配对Δd=-1 nm、跨模型拒绝但保留原值、文件内81坐标、PNG/JSON及来源、原件SHA、键盘/390/reduced-motion。当前修订再做最终回归。后端扩大组初次18通过2跳过1失败，失败为Windows默认GBK读取UTF8契约；以PYTHONUTF8=1重跑，不修改科学计算以迁就测试。

- 扩大旧浏览器回归第一轮4通过3失败：两项仍按旧表格tr定位科研履历，一项未先展开新增逐片测量折叠区。只调整这三处交互选择器/展开步骤，保留历史、循环、原件、跳转断言，不回退用户授权的时间轴和减法布局。另补实验结果在模型拒绝比较时直接读取原始测量均值，仍不派生差值。

### 正式前端升级最终交付

- 生产前端11个源码文件的局部改造完成：AnalysisView、ScientificPlot、LabMetric、SampleExperimentHistory、SampleResearchReview、SampleHistoryView、ExperimentResults、DashboardView、AIAssistant、lab-ui.css、main.ts；Element Plus/ECharts继续复用，新增依赖0，未新增导航/业务模块/后端API。
- 最终类型/正式构建通过（final-typecheck.log / final-build.log）；新增浏览器5通过、原有浏览器7通过（final-browser.log、existing-browser-final.log）；后端19通过2跳过（backend-regression-utf8.log）。浏览器源数据走真实解析器/API，隔离ale_workbench_test与原件目录且事务回滚；实际原件4点已读入隔离库验证，81点情景为测试工作簿，不是原始附件验收。
- 64份引用资产已同步frontend/dist且逐文件SHA一致（deployment.log/json），保留旧资产与before恢复点，不启动/重启正式后端。生产43表2原件前后指纹完全一致（safety-verification.log）。没有本人正式账户写操作。
- 引用资产图gzip合计777,461→784,622字节，约+7KB；非首屏大小，既有大chunk提示保留。前后16张桌面/窄屏对照及实际原件摘要可在reports/ui-upgrade/前后对照.html查阅；各阶段截图、命令和日志均保留。操作手册与现有产品报告已增量更新。
- 初轮GBK读契约、旧表格定位及折叠可见性测试失败已记录并重跑通过；没有删除数值/来源断言。真实81点旧归档、本人的正式账户操作和正式服务跨进程重启仍未执行。完整范围、依赖取舍、体积、回退和边界见reports/产品重整方案.md“正式前端可视化与交互升级（P0—P4）”。

## 2026-10-24 V2.2 P0–P2 增量实施（进行中）
- 核对任务书、原工作台 Vue/Python/MySQL、旧设计文件、竞赛 Excel；生产43表2原件只读基线 reports/ale_v2_2/safety-before.json。当前3账户21样品7执行；无Git，H:\AGENTS.md缺失。未继承历史清理授权。
- 修改：backend/app/main.py，新增 quick_models.py/quick.py/quick_dataset.py；迁移0014_quick_record.sql（只在ale_workbench_test应用）；前端router/AppShell增量接入QuickRecordView、QuickDatasetView、QuickTemplatesView、QuickNumber、quick/model.ts与quick.css。修改前副本before/。
- 不建虚假批次/样品，沿用process_id，R1/R2/N2及实际时间同步原执行。PL通道未确认不赋化学含义；有效循环与程序循环分开；匿名结果显式连续关联、修订、幂等、版本检查。
- 实际测试：backend/.venv-win/Scripts/python.exe -m pytest tests/test_quick_v22.py -q；最终backend-fourth.log 11 passed（真实MySQL事务回滚）。之前权限/双外键JOIN/幂等默认UUID失败日志均保留。类型检查与隔离Vite构建通过，既有500kB包警告保留。生产dist未覆盖。
- 真正启动：独立数据库Python8012、Vite5182，使用测试专用身份（凭据只存backend/.runtime）；浏览器验收正在执行，首次发现原生select标签包含option文本导致精确可访问名称不稳定，正在补明确aria-label并复测。不是正式账户验收。
- 证据与进度：docs/ale_v2_2/00_current_system_audit.md、reports/ale_v2_2/；生产原件未动，未操作设备或发送科研数据到外网。

## 2026-10-24 V2.2 P3–P6 交付与用户即时精简
- 用户最新截图明确取消SiN/SiO₂快捷按钮、外层总循环输入、步骤操作行、增加步骤/工艺组按钮。已从正式快录移除；原有变长步骤、多组和外层值完整保留。“结果1”改为膜厚测量，字段简化为样品标识、薄膜材料、刻蚀前/后膜厚、本段有效循环次数、前膜厚来源、数据性质；增加结果行改为添加测量样品。
- 实际修改源码19个文件与SHA/diff：reports/ale_v2_2/source-manifest.json、source-changes.patch；修改前before/，原前端before/frontend-dist。新增6份docs/ale_v2_2合同；真实迁移0014_quick_record.sql引用原process_id与所有权。生产无新增UI运行依赖，axe仅测试目录。
- 真实MySQL：backend-final.log 63 passed/1 skipped；最后受影响backend-last-affected.log 13 passed，两组重叠不相加。旧专业浏览器7 passed（样品双向履历、重复执行、五片节点、导入等），old-browser-regression.log。唯一跳过为未挂载外部原解析样例；没有将跳过写通过。
- 独立进程Vite5182/Python8012和真实MySQL、测试专用身份/原件目录；浏览器先完整闭环，再按用户新布局在Vite与实际编译8012重复通过。browser-simplified-built-final.log验证取消控件、科学字段、3次快速点击仅1 POST、保存刷新、连续200、真实Excel确认、多样品、旧第6步、数据集筛选、全部导出。旧增删按钮证据只作为用户取消前的历史证据，不声称新页面仍有。
- 六视口1920/1366/1280/1024/768/390与真实Edge tabs.setZoom 125/150/200%通过；最终四页面@axe-core/playwright扫描violations=[]；人工截图/键盘/焦点/两真实标签页冲突及网络失败保留均有证据。final_data_checks.py实际验证2 Run/6结果多条件筛选、空导出、24步/2组/3样品长备注390、真实坏文件错误。没有成功API Mock。
- 迁移：测试up与重复up通过；生产前43表344行完整备份实际恢复到新*_test，322行业务逐字段核对；生产0014仅增加6空表及账本，原科学值保持。旧1.8入口+旧dist在独立恢复库实测health/login/setup，采用保留新增表与数据的应用回退，禁止DROP，未执行物理删表down。生产迁移及旧版回退证据migration-production.log、backup-restore-result.json、rollback-and-startup.json。
- 正式219份构建文件逐SHA同步并保留旧资产，typecheck-simplified-final.log与build-simplified-final.log通过；原启动器实际启动并将受信PID21152重启至15420（production-startup-final.log），正式http://127.0.0.1:8000/quick可用。隔离Python跨进程重启后旧Run4705/4706指纹一致，persistence-after.json。没有自动刷新用户页面或写正式验收Run。
- 原件核对：竞赛125条材料数据行（Al2O3 113/In2O3 5/HfO2 5/Ga2O3 2），全部实验ID格为空，日期为空行曾导致首轮审计漏计，最终按实际材料数据行修正。SHA 2b2199718a29d6ca9675c8c2a7d84e057fd91dd62151d00e54de52a6767e8686不变；原第3行EPC -1.585 vs重算-0.7925只报告不修正。2正式原件哈希保持；实际原件仅隔离预览并取消映射。
- 最终生产指纹：原40张非会话业务表不变；已有浏览器会话仅refresh_jti_hash/expires_at正常轮换，已逐字段核准，不能再笼统称所有41业务表完全不变。用户正式页面创建的3条新材料保留；生产快录仍0、隔离验收身份不存在于生产。详见production-safety-result.json，未清理用户数据。
- G1按最新范围：原68项64 PASS/4 ADJUSTED_BY_USER（A06/A07/A11/D16），逐项原要求/实际/证据见final_acceptance.md与acceptance-ledger.json。G2真实数据体检与UI巡检完成；训练门槛未满足，G3不运行、不编指标。H:\AAA_lab\Algorithms已只读核对，其A/B脉冲单位s与本设备原始ms/未确认通道不能盲接。未取得独立设备照片，不猜化学身份，不操作设备，不外发科研数据。
- 稳定交付：export_samples/{competition_export_software_acceptance.xlsx,full_runs_software_acceptance.json,ml_wide_software_acceptance.xlsx,dataset_readiness.json/html}；当前样例18次软件验收Run/24结果，synthetic筛选、eligible=0，不能冒称真实科研训练结果。UI对照ui-review.html及全部截图/trace保留。正式账户写操作未执行，不把隔离验收当正式账户验收。

### V2.2 最终交付补记
- 最新截图精简后，编译服务browser-delivery.log再次全部通过；axe-delivery.log四页面零违规。真实Excel补录与全部下载仍走实际服务/独立MySQL。
- 最后修复精度边界：提交Decimal原始文本而非先转JS浮点；R1/R2按原执行列2位、N2按3位小数校验，超精度就地保留输入并报错，防止SQL静默舍入。程序循环未知时不按0产生不一致提示。backend-delivery.log 13 passed，类型与构建最终日志通过。
- 完整JSON补齐有权限的导入预览/逐块确认历史，保留同次确认的多阶段来源及测点；测试已核对。软件样例最新22 Run/33结果，稳定文件及最终实际条数以final_acceptance.md为准。
- 最新生产启动日志production-startup-delivery.log核验受信重启；当前HTTP首页SHA与部署文件一致。资产精确清单deployment.json，最新源码19文件SHA在source-manifest.json；无需更改原启动方式。原件与原科研业务指纹继续保持，正式页面正常会话刷新及用户创建的新材料已如实记录。

## V2.2 完整目标继续审计（不沿用64+4通过口径）
- 上一目标回合归类为有进展：真实代码、迁移、浏览器与证据均已产生；但完整目标仍active，64 PASS+4 ADJUSTED不能视为68全部通过。
- 当前验收矩阵由recheck_audit.py重建，仅接受PASS/FAIL/BLOCKED/NOT_RUN及逐项明确证据；先全部NOT_RUN，旧结论保留recheck/previous-acceptance.*，不删除失败证据。
- 同时满足截图精简与完整工艺编辑：主表不恢复被框出的行/按钮，新增按需打开的QuickProgramEditor真实弹窗，含外层循环、增加/插入/复制/删除/移动步骤、组重复与排序、撤销、应用/取消。主表只保留编辑工艺结构入口。
- 编辑弹窗为独立内存草稿，应用后再由原保存事务入库；关闭/导航/刷新均检查尚未应用修改。类型检查已通过，实际浏览器待复核，未把实现写成通过。

### 完整目标复核：结构、初始化导航、体检与长工艺导出
- 真实结构弹窗browser_structure.py已完成A06/A07/A11/D16逐项断言，MySQL实际Run4835回读外层3/A组7/B组2及所有稳定步骤ID；新增/插入/复制/整列移动/含值确认删除/空列删除/撤销/焦点均验证，主表保持精简。case-evidence-structure.json为明确证据，不沿用ADJUSTED。
- 发现并修复真实P1：初次加载前脏状态误判导致导航卡在未保存确认。增加ready gate、失败禁保存、同页query切换保护；真实浏览器在初始请求仍可能pending时立即导航已成功。首次卡住的测试进程在核实活跃及确定原因后中止，readiness-aborted-reason.txt保留，不算通过。
- 体检补齐逐X/y字段缺失（零值不算缺失）、材料/设备/连续序列分组、真实/合成/未知和质量状态、来源单位异常、真正计算的跨split交集。实际3 Run/4测量/2关联组，缺失N2=2、缺失R1=3、均匀性缺失=2，unknown不当真实；中文逐条原因与可读HTML在390px复核。E05/E06/E07/C09/E08已新增具体证据。
- 检出并修复窄屏转换时旧主区域margin动画产生403px瞬时横溢出，移动断点取消该布局过渡，未隐藏页面或关闭检查。
- 复现真实长工艺导出缺陷：6组×100步的宽表X_recipe_json被openpyxl截至32767字符，JSONDecodeError。日志large-recipe-reproduction.log。修复为明确规范化引用、完整有序附加步骤/程序行、完整JSON保留；新增大文本片段承载与单格硬校验，禁止静默截断。feature schema升级2.2.2/mapping conservative-2，重复检测仍用完整配方hash。
- 快录校验错误现在保留服务端字段路径并转换为A组第n步/中文字段名，避免只给Invalid request。模板与上传预览的写入明确要求记录所有者，管理账户只读权限不再意外生成无权确认的来源附件；空白模板名服务器拒绝。
- 完整验收仍active：矩阵只允许PASS/FAIL/BLOCKED/NOT_RUN，当前9项明确PASS，其余待逐项核对。旧自动64+4生成器已归档，finalize.py仅调用真实recheck_audit，不再自动填PASS。最终发布/构建/全矩阵复核尚未完成。

### V2.2 当前源码逐项复核续记
- browser_records.py真实API/浏览器/原processes投影验证材料、时间、备注、EPC、多片与三段250→230累计，以及独立复制。首次第三段失败查明为保存期间输入可编辑，响应会覆盖此时输入；主表改用busy原生fieldset锁定。复测records-built.log全部断言通过。
- browser_reliability.py实际网络延迟/offline与明确HTTP500失败注入验证输入保留、重试及双标签页CAS冲突；没有伪造成功响应。下载冲突草稿可回读，模板仅复制参数。Vite全部通过；首次编译重跑因多套脚本短时间登录触发10次/分钟限流，失败日志保留，需串行重跑。
- 实际非法数字提交时，busy锁定导致focus无效；在finally解锁后nextTick回到首个错误字段，visual-focus-repro.log保留，visual-final/visual-built验证恢复。
- 两工作表量测预览未改值；45.30与45.27并排核对后逐片确认，第三片/另一Run不变；快速三击仅1POST，原SHA再上传再确认不再增版本。导出2Run6测量、28列逐字逐序核对竞赛原表，3组与第6步完整，公式前缀安全，原件SHA全部不变。见import-export.log及verified-export.*。
- 新独立ale_v22_roundtrip_7a7e6edd_test复制原43表344行，正常迁移up、原子RENAME保留扩展表的down、恢复名称再次up均逐值核对旧行。无DROP、不操作生产，migration-roundtrip.json。此回退方式明确区别物理删表down。
- 完整写接口安全矩阵实测发现跨所有者PUT先触发材料422；改为先校验并锁定目标所有权，避免先校验外来数据。18项快录后端测试通过，见backend-security-final.log。空{}文件来源伪造也已复现并拒绝，empty-provenance-repro.log保留。
- 六视口、新结构Modal、键盘Tab/ShiftTab、焦点回位、错误值保留及按钮hover/active逐项脚本通过，人工检查发现专业概览浅底白标题，已修复为海军蓝正文/青绿提示。原生Edge放大截图裁切尚在复核，不能只凭无横溢断言视觉通过。
- 上轮专业回归曾与构建目录替换及已提交的独立API用例并发，出现404和数据库指纹变化；这是验收编排问题，未弱化旧回归数据库不变断言，最终须停止并发写后单独重跑。当前矩阵不自动填通过。

### V2.2 最终范围验收与部署完成
- 逐项矩阵：68 PASS / 0 FAIL / 0 BLOCKED / 0 NOT_RUN。不是64+4调整，recheck_audit.py只汇总明确case-evidence文件，final_acceptance.md逐项原要求/实际/证据均保留。
- 当前后端完整选定回归backend-final.log：107 passed / 1 optional external-parser sample skipped；快录安全矩阵含18项，计数已包含在107内不相加。旧专业浏览器严格串行regression.log：7 passed，49表与原件指纹断言未降低。前期并发导致审计/会话变化的失败保留backend-concurrent-audit-repro/regression-concurrent-data-repro.log。
- 当前编译8012真实用例records-built、reliability-built-final、visual-built-final、persistence-browser均通过。七个axe目标含新结构弹窗/体检展开/专业概览，最终violations全空；专业概览对比度修复已验证。Modal审计等待进入动画结束，原中间帧半透明报告保留；未关闭contrast规则。
- 人工已查看窄屏主表/弹窗、桌面网格、专业概览、390可读体检、125/150/200真实Edge原生视口截图。原全页截图真实zoom裁切不能代表成品，改用原生Page.captureScreenshot；等待布局动画稳定的专业概览截图未遮挡。按钮六状态、Tab/ShiftTab、焦点回位、A组#3非法Pulse保留及定位有日志/Trace。
- 独立Python重启前后2Run API完整指纹75e44bc2db03b20cc0e0be306ef15d15c6afa628df524ab64f43d8155bdcaeed相同；逐字段匹配MySQL JSON，浏览器重复刷新核对双温区/第6步/零值/45.27膜厚。断网/500/1200ms真实网络延迟及恢复重试通过。
- 最后源码98文件SHA绑定71构建文件，vue-tsc/Vite通过。recheck/deploy_verified.py核对源码与每份构建后先复制资产再原子切换index，旧资产/入口保留。原start-workbench.ps1实际核准重启PID28696→3736，8000正式入口及4个引用资产HTTP200/SHA一致，production-http.json。
- 5个实际HTTP下载统一筛选2Run/6条synthetic测量/可训练0，保存在export_samples，文件SHA/格式回读见recheck/delivery-artifacts.json，旧22Run样例归档recheck/previous-export-samples。JSON、28列XLSX、宽表、体检JSON/HTML均来自同一筛选。未修改原竞赛表或生产原件。
- 科学与生产边界：40张旧非会话业务表及2原件保持，已有会话只允许正常refresh字段轮换；保留用户新材料，测试身份不在生产。通道身份未确认/无实际可训练数据，不训练、不造指标、不操作设备、不外传。最终安全日志与SHA复核继续见recheck/production-safety.log。

## 2026-10-26 实际源下拉与用户明确授权的数据库重置
- 用户明确要求去掉“参数/#n·未启用”行、使用HF/TMA等实际源并支持手动添加、清空工作台数据库、创建管理员与测试账户。清空范围已声明为ale_workbench，保留原文件/迁移账本；其他数据库不动。此次是用户明确授权清空，不是自动清理生产。
- 新增0015_quick_sources.sql及GET/POST /quick/sources，所有者隔离/去重/校验；migrate.py的0014外键校验改为仅检查原六表，避免扩展源表导致旧校验误报，并增加0015验证/最小授权。旧已应用SQL未修改。
- 主表隐藏整行状态表头但保留可访问语义；源字段改用复用QuickSourceSelect，在主表/结构弹窗均支持点击/筛选/清空，顶部添加实际源持久化，不推断或转换PL1/PL2。无新依赖。
- backend.log 20 passed（含原18快录回归），vue-tsc/Vite通过，99源文件SHA绑定71份构建。独立真实HTTP/MySQL/browser完成HF/TMA/自定义源添加/去重/保存回读、第6步移动撤销、390px下拉；axe无违规、无JS错误。初次测试曾在弹出关闭动画中匹配两个listbox选项，改为按该源输入关联的listbox精确定位，不弱化行为断言，失败日志保留。
- 清空前完整备份 H:\ALE_AI\backups\before_migration_20261026T012515471443Z，实际恢复50表/视图并逐值验证；恢复副本ale_reset_04634acb23_test先做清空演练。备份文件SHA及正式原件SHA验证后，正式库事务DELETE清空所有旧业务/账户/会话/密钥配置，保留schema_migrations/schema_migration_attempts；新建admin管理账户与test测试账户，各2条HF/TMA源目录。未DROP/TRUNCATE、未重置自增ID、未动原始文件。
- 生产实际空库验证所有科学业务表0，用户仅2；首次登录自动生成1条无密钥默认ai_config及新会话/登录审计，已校验其为默认新值而不是旧配置残留。旧内容删除与新运行记录明确区分，验证脚本首次严格零值断言发现该初始化后补充默认值/无key/版本1的核对，未删除新运行记录作假。
- 部署每份构建SHA核对并保留旧资产，原start-workbench.ps1实际启动8000/PID40616。两个正式新账户实际登录及权限验证通过，管理员仅见2用户，测试账户不能进入用户管理；各自源目录隔离。桌面/手机正式截图已查看，原件2份SHA保持，未向正式库写验收实验。新账户密码仅在私有runtime文件与交付消息中提供，不进报告/日志。
- 当前交付报告 reports/source_catalog_20261026/交付报告.md；旧68项报告加历史范围说明，不把本次有限回归冒称68全量重跑。

## 2026-10-27 启动端口冲突修复
- 复现原默认8000启动退出1，证据 reports/startup-port-20261027/reproduction.log。只读Win32_Process确认监听PID23136的父进程30016来自另一项目 H:\AI For research institute\Silver-economy\.venv\Scripts\python.exe，不接管或停止。
- 最小修改 start-workbench.ps1 默认端口8000→8001，同步启动说明.md顶部当前入口；显式-Port及进程身份/可信记录保护保留。启动工作台.cmd继续转发原脚本，无业务代码、数据库迁移或原件修改。
- 实际Windows启动默认8001成功，Verified PID13852/schema2/1.8.0；再次 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-workbench.ps1 返回0并Reusing同PID。pip check通过、PowerShell解析无错、/health数据库ok、/login HTTP200；原8000 PID23136仍在。证据startup.stdout.log/startup.stderr.log/reuse.log/verification.json/original-process-after.json均在同目录。未执行正式账户业务验收。
- Codex从PowerShell7用Start-Process发起Windows PowerShell5.1时首次继承模块环境导致Get-FileHash不可见；验证启动时显式导入系统WindowsPowerShell Utility模块后通过。直接powershell.exe -File重复启动无需额外导入并通过，未为工具环境问题改产品脚本。
