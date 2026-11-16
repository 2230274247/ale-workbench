# 实施计划（IMPLEMENTATION_PLAN）

## 开发阶段与里程碑

### M01 数据管线
- 合成数据生成、分组划分、真实数据读取、字段检查、缺失值处理。
- 里程碑：能产出防泄漏的 train/val/test 数据。

### M02 特征工程
- 特征选择、类别编码、数值标准化、目标构建、预处理器保存/加载。
- 里程碑：训练和预测用同一套预处理。

### M03 传统模型基线
- 岭回归、SVR、随机森林等表格模型 + 评价。
- 里程碑：得到可对比的 Baseline 指标。

### M04 PyTorch MLP
- 第一个可训练的神经网络。
- 里程碑：MLP 能训练并评价。

### M05 Transformer
- Embedding、Attention、MHA、FFN、Residual、LayerNorm、Encoder、回归头。
- 里程碑：Transformer 能训练并评价。

### M06 训练与优化
- Dataset/DataLoader、Optimizer、Loss、单轮训练、验证、EarlyStopping、Checkpoint、调参。
- 里程碑：完整训练流程 + 模型保存。

### M07 前向预测与后向优化
- 加载模型预测、约束内参数搜索。
- 里程碑：给定目标能反推工艺参数。

### M08 FastAPI 接入
- 前向预测 API、模型管理、ALE Workbench 集成。
- 里程碑：通过 API 完成预测。

## 依赖关系

M01 → M02 → M03（基线）→ M04（MLP）→ M05（Transformer）→ M06（训练优化）→ M07（预测/优化）→ M08（接入）

其中 M03 与 M04/M05 可并行（基线独立于神经网络）。
