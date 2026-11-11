# 机器学习特征合同与训练门槛

feature_schema_version=ale.quick.features/2.2.2；mapping_version=competition28/conservative-2。观测单位为Run×结果行，物料/设备分别统计，未知值保留null。X包含材料、设备、独立R1/R2/N₂/绝对压力、实验前实测膜厚、有效循环及有序动态recipe JSON；内含行政UUID已剔除。y为净膜厚损失、EPC、均匀性；日期/当日序号/结果ID/后膜厚不作为X。

候选必须正式、明确real_experiment、approved、有材料/设备/目标、周期口径明确、非未核对承接参考；均匀性定义不明、报告与重算EPC差异、通道物理映射不明均列排除或审核原因。当前没有已确认通道映射，全部recipe标unsupported_recipe_unconfirmed_channel_mapping，不把格式就绪冒充科学可训练。

每个独立运行有服务器sequence_id；继续上一段继承，独立复制重建。所有同运行多结果及显式连续链共享meta_leak_group。提供sha256(sequence_id)固定80/10/10建议桶与组交集检查，属于可复验的分组建议，不表示已训练或有足够有效组。后端测试实测三段与同运行多结果不跨桶。未声明的跨序列同片/物理批次相关性需要进一步人工审核。

一键体检统计材料、设备、真假/遗留、X/y缺口、EPC差异、均匀性口径、重复特征/目标、连续组；可下载JSON和浏览器HTML。全部软件验收值标synthetic或unknown，未混作真实候选。没有性能图、预测值或伪造指标。

只读核对H:\AAA_lab\Algorithms：真实项目src/aleopt下有feature modes、data revision、lab contract；其固定A/B脉冲以s表示，本工作台原始设备网格是ms且源身份未确认，因此禁止盲接训练。README也明确真实验证R²为负且历史重复使用不恢复独立性。没有运行训练、写入算法项目或调用设备。前向/反向/主动学习保持数据门槛说明，G3基线条件不满足。

长配方超过Excel单格32767个UTF-16单元时，宽表显式改为完整附加步骤引用、保留配方SHA及排除原因；程序/组/每步按原序完整输出。超长附加JSON使用可重组片段；不能输出的控制字符拒绝导出并引导完整JSON，不静默截断。
