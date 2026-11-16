# ALE Transformer 实战开发课程

> 目标：亲手编写、训练、部署一个面向 ALE 实验数据的 Transformer 回归模型，
> 实现前向预测与后向工艺参数优化。学习过程就是最终项目开发过程。

## 开发路线（以最终系统为目标，非理论章节）

### 第一阶段：ALE 数据管线
- 读取真实 ALE 数据，构建 X / y。
- 数据清洗、标准化、按 `sequence_id` / `meta_leak_group` 分组划分。
- 防止数据泄漏。
- 文件：`src/data/dataset.py`、`src/torch_basics/tensors.py`

### 第二阶段：传统机器学习基线
- 岭回归、SVR、随机森林等表格模型。
- 建立评价体系（R²、MAE、RMSE）。
- 文件：`src/evaluation/metrics.py`、`src/training/loop.py`

### 第三阶段：PyTorch MLP
- 第一个真实可训练的神经网络。
- 文件：`src/model/regressor.py`

### 第四阶段：Transformer
- Embedding → Attention → Multi-Head Attention → Encoder → 回归输出层。
- 文件：`src/attention/scaled_dot_product.py`、`src/attention/multi_head.py`、`src/model/encoder.py`、`src/model/regressor.py`

### 第五阶段：模型训练与优化
- 训练、验证、调参、模型保存、对比分析。
- 文件：`src/training/loop.py`

### 第六阶段：ALE 系统接入
- 前向预测 API、模型管理、后向参数优化。
- 文件：`src/inference/forward.py`、`src/optimization/search.py`

## 教学方式约定（快速项目实战模式）

1. 功能目标 → 文件位置 → 可用代码 → 关键原理 → 必要性和错误案例 → 亲手输入 → 运行测试 → 下一任务。
2. 直接提供可用于最终工程的代码片段，不写无关演示代码。
3. 重点讲算法原理、关键参数、数据流、Tensor 维度、工程设计。
4. 不逐行解释基础 Python 语法。
5. 学习者亲手输入所有算法代码，AI 不直接改算法源文件。
6. 不频繁理论考试，优先保证开发进度。

## ALE 项目约束（贯穿全程）

- `X_` 字段 = 输入特征；`y_` 字段 = 预测目标；`meta_` 字段 = 追踪/分组，不作模型输入。
- 关注 `sequence_id` 与 `meta_leak_group`，避免同一实验链被拆进训练/测试集。
- 目标字段：净减薄、EPC、均匀性（以数据集定义为准）。
- 训练/验证/测试严格区分；标准化参数只从训练集拟合。
- 评价同时看 R²、MAE、RMSE。
- 先建传统机器学习 Baseline，再研究 Transformer；不默认 Transformer 一定更优。
