# 项目总览（PROJECT_OVERVIEW）

## 最终目标

交付一套完整、真实可训练、可评价、可预测，并能接入 ALE Workbench 的 Transformer 算法系统。

## 交付要求

1. ALE 数据读取
2. 特征工程
3. 数据集划分（防泄漏）
4. 传统模型基线
5. PyTorch Transformer
6. 完整训练流程
7. 模型评价
8. 模型保存和加载
9. 前向预测
10. 后向参数优化
11. FastAPI 接口
12. ALE Workbench 集成

所有功能必须通过实际运行验证。

## 关键约束

- `X_` 字段 = 输入特征；`y_` 字段 = 预测目标；`meta_` 字段 = 追踪/分组，不作模型输入。
- 关注 `sequence_id` 与 `meta_leak_group`，避免同一实验链被拆进训练/测试集。
- 目标字段：净减薄、EPC、均匀性（以数据集定义为准）。
- 训练/验证/测试严格区分；标准化参数只从训练集拟合。
- 评价同时看 R²、MAE、RMSE。
- 先建传统机器学习 Baseline，再研究 Transformer；不默认 Transformer 一定更优。
- 不重建数据库、不重写历史、不自动清理生产数据；测试用独立 *_test 数据库与独立原件目录。
- 不得擅自假设工艺步骤一定具有时间序列含义。
- 真实 ALE 数据接入前，先核实数据字段、目标变量和数据组织形式。

## 当前数据现状（来自 docs/ale_v2_2/05_ml_feature_contract.md）

- 观测单位：Run × 结果行。
- X：材料、设备、独立 R1/R2/N₂、绝对压力、实验前实测膜厚、有效循环、有序动态 recipe JSON。
- y：净膜厚损失、EPC、均匀性。
- 当前没有已确认通道映射，全部 recipe 标 unsupported_recipe_unconfirmed_channel_mapping。
- 真实项目 R² 为负，历史重复使用不恢复独立性。
- 结论：先用合成数据跑通全链路，真实数据接入时只换数据源。
