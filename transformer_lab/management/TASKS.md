# 任务清单（TASKS）

> 状态：TODO / READY / IN_PROGRESS / IMPLEMENTED / TESTED / ACCEPTED / BLOCKED
> 代码生成=IMPLEMENTED，测试通过=TESTED，用户确认=ACCEPTED。

## M01 数据管线

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M01-T001 | 合成数据生成器 | ACCEPTED | - | `src/data/dataset.py` | 输出 X(180,8)/y(180)/groups，测试通过 |
| M01-T002 | 按组整组划分 train/val/test | READY | M01-T001 | `src/data/dataset.py` | 三集合组号无交集，行数之和=总数 |
| M01-T003 | 真实数据读取（字段检查） | TODO | M01-T002 | `src/data/dataset.py` | 能读取并校验 X_/y_/meta_ 字段 |
| M01-T004 | 缺失值处理 | TODO | M01-T003 | `src/data/dataset.py` | 缺失值按策略处理，不静默丢弃 |

## M02 特征工程

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M02-T001 | 数值标准化（fit/apply） | ACCEPTED | - | `src/torch_basics/tensors.py` | 标准化后均值≈0、标准差≈1 |
| M02-T002 | 类别编码 | TODO | M01-T003 | `src/features/` | 类别特征转数值 |
| M02-T003 | 目标变量构建 | TODO | M01-T003 | `src/features/` | 从 y_ 字段构建目标 |
| M02-T004 | 预处理器保存/加载 | TODO | M02-T001 | `src/features/` | 预处理参数可持久化 |

## M03 传统模型基线

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M03-T001 | 评价指标（MAE/RMSE/R²） | ACCEPTED | - | `src/evaluation/metrics.py` | 指标计算正确 |
| M03-T002 | 岭回归基线 | TODO | M01-T002, M03-T001 | `src/training/` | 能训练并输出指标 |
| M03-T003 | 随机森林基线 | TODO | M01-T002, M03-T001 | `src/training/` | 能训练并输出指标 |

## M04 PyTorch MLP

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M04-T001 | MLP 模型 | TODO | M01-T002 | `src/model/regressor.py` | 前向传播 shape 正确 |
| M04-T002 | MLP 训练 | TODO | M04-T001, M03-T001 | `src/training/loop.py` | 能训练并评价 |

## M05 Transformer

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M05-T001 | Embedding | TODO | - | `src/model/` | 特征→d_model 向量 |
| M05-T002 | Scaled Dot-Product Attention | TODO | - | `src/attention/scaled_dot_product.py` | 注意力权重正确 |
| M05-T003 | Multi-Head Attention | TODO | M05-T002 | `src/attention/multi_head.py` | 多头拼接正确 |
| M05-T004 | Feed Forward Network | TODO | - | `src/model/` | 前馈层正确 |
| M05-T005 | Residual + LayerNorm | TODO | - | `src/model/encoder.py` | 残差连接正确 |
| M05-T006 | Transformer Encoder | TODO | M05-T003~T005 | `src/model/encoder.py` | Encoder 前向正确 |
| M05-T007 | 回归头 | TODO | M05-T006 | `src/model/regressor.py` | 输出目标值 |

## M06 训练与优化

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M06-T001 | Dataset/DataLoader | TODO | M01-T002 | `src/training/` | 能产出 batch |
| M06-T002 | Optimizer/Loss | TODO | - | `src/training/loop.py` | 损失可计算 |
| M06-T003 | 单轮训练 + 验证 | TODO | M06-T001, M06-T002 | `src/training/loop.py` | 训练/验证循环正确 |
| M06-T004 | Early Stopping | TODO | M06-T003 | `src/training/loop.py` | 过拟合时提前停止 |
| M06-T005 | Checkpoint 保存/加载 | TODO | M06-T003 | `src/training/` | 权重+预处理参数一起保存 |

## M07 前向预测与后向优化

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M07-T001 | 前向预测 | TODO | M06-T005 | `src/inference/forward.py` | 加载模型并预测 |
| M07-T002 | 后向参数搜索 | TODO | M07-T001 | `src/optimization/search.py` | 约束内反推参数 |

## M08 FastAPI 接入

| 编号 | 任务 | 状态 | 依赖 | 文件 | 验收标准 |
|---|---|---|---|---|---|
| M08-T001 | 前向预测 API | TODO | M07-T001 | `src/inference/` | API 返回预测 |
| M08-T002 | 模型管理 | TODO | M06-T005 | `src/inference/` | 模型可加载/切换 |
| M08-T003 | ALE Workbench 集成 | TODO | M08-T001 | - | 通过 API 完成预测 |
