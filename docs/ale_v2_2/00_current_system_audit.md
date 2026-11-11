# V2.2 当前系统审计（2026-10-24）

源码 H:\ALE_AI，无 .git，无法报告分支或生成 Git diff；保留修改前副本和 SHA 文件清单。H:\AGENTS.md 缺失，继承用户消息中的完整约束及项目 AGENTS.md。任务书文件实际名称为 Downloads/ALE 工作台 V2.2｜Codex 超详细实施与验收任务书.md；其内容作为本次用户明确要求的功能规格，历史报告中的清理授权不继承。

已核对核心产品规范、进度日志、此前 UI/UX、设计规范、产品重整、第一轮、操作手册、三账户、数据库报告的现状相关章节，并以真实代码和实时库优先。生产基线 43 表、3 用户、21 样品、7 执行、2 原件；详见 audit.json 与 safety-before.json。Vue 3.5 / Vue Router 4.5 / Pinia 3 / Element Plus 2.11 / Lucide / ECharts 已存在，不新增运行期 UI 库。Python 使用项目 .venv-win；MySQL 8.4.11，端口 3307。

真实模型 processes 已允许 batch_id / plan_id 为空，不必伪造实体。R1/R2/N2/时间/notes 复用原执行列。快录扩展表引用同一 process_id；动态工艺与匿名结果存版本化 JSON，避免把未确认的源通道映射到旧化学字段。没有写入原 process_samples 或虚构已参与样品。原流程保留为专业模式。

原件与竞赛 Excel 只读。参考 Excel 的 28 列表头真实回读一致；SHA256 2b2199718a29d6ca9675c8c2a7d84e057fd91dd62151d00e54de52a6767e8686。首轮按非空日期计数仅为116（合并日期行漏计），不能当成全表记录数，后续以实验 ID 和实际数据行重新统计。附件截图为页面设计；当前消息没有单独可识别的设备照片文件，不据此推断 PL1/PL2 化学身份。H:\AAA_lab\ALE_AI_Optimization\main.py 实际仅为 PyCharm Hello 示例，不能声称已接入 GPR。

安全策略：所有写入测试显式 ALE_DB_NAME=ale_workbench_test、ALE_REQUIRE_TEST_DB=1、ALE_ENVIRONMENT=testing，原件路径 storage-test/v22 或 pytest tmp。生产表与文件只读指纹保护。隔离 DDL 使用现有管理员凭据读取函数（不输出），仅新建六张扩展表并赋予已有 ale_app SELECT/INSERT/UPDATE。应用账户自身无 CREATE 权限，该失败已记录并改用既有迁移凭据。禁止删除原数据。

阶段验收：后端专项初次5通过5失败，修复显式 JOIN/权限后10通过1失败，修复幂等默认键后11通过；保留所有失败日志。真实 Vite 5182 / Python 8012 独立进程已启动；前端类型和隔离构建通过。最终结果以 final_acceptance.md 为准。
