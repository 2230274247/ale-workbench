# 兼容数据扩展与回退

0014_quick_record.sql 仅 CREATE TABLE IF NOT EXISTS 六张表：quick_materials、quick_runs、quick_revisions、quick_templates、quick_imports、quick_exports；10个外键。没有修改旧列、重建旧表或回填历史科学值。

quick_runs.process_id 复用 processes 主键。processes 的 owner/operator、R1/R2/N₂、UTC起止时间、notes 与 row_version 继续作为既有执行投影；程序、匿名结果、材料和本地日期语义只由扩展快照定义。旧化学步骤字段不会收到未经确认的通道映射或假样品。专业详情明确链接回快录；旧编辑接口对快录托管记录返回409，防止两套编辑器产生事实分叉。旧专业记录编辑路径不变。

每次保存同一事务包含执行、快照和完整修订；父用户锁串行化当天序号/幂等意图，日期序号与请求键各有唯一约束。请求指纹忽略可由服务端生成的稳定对象UUID，保留科学字段与连续来源。更新必须匹配 row_version，旧修订永久保留。序列身份由服务器创建/继承，旧运行不能随意改连续链。

迁移沿用 database/migrate.py 的一致快照备份、校验和账本、原字段核对与应用账号授权。增加 --database 仅允许现有生产库或显式 *_test。应用账号不拥有DDL权限，新表仅赋予SELECT/INSERT/UPDATE。测试库实际up及再次up均通过，原115行字段保持。生产迁移前完整备份已在新建ale_v22_restore_20261024_test实际恢复（43表344行；322行业务逐字段比较，账本22行另保留），不是仅声称有备份。

生产实际迁移日志 migration-production.log：只追加0014账本与六个空表，原322行业务字段保持。production-safety-result.json核对原40张非会话业务表与2原件指纹；已有正常会话仅refresh_jti_hash/expires_at轮换。用户新增材料保留，验收身份不进入生产。

回退采用非破坏性应用回退：停止本轮已确认的服务，恢复before中的旧源码与before/frontend-dist的index/引用资产，重启原版。保留0014扩展表与修订，不执行DROP、不撤销历史；需要再次启用时可直接重启新代码。测试通过旧专业浏览器回归与原业务指纹证明兼容。最终复核另在全新ale_v22_roundtrip_7a7e6edd_test完成结构回退：六张新增表用单条原子RENAME改为rollback_名称，43张旧表及344行仍逐值一致；恢复名称后正常迁移再次校验。它是保留数据的down/up测试，不是物理删表down。没有在生产执行该回退。证据recheck/migration-roundtrip.json。
