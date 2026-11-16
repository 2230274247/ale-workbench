# 交接报告（同步 ChatGPT 用）

> 当学习者说「同步 ChatGPT」时，把本文件内容整理成完整进度报告交给 ChatGPT。

## 项目架构

- 独立学习工程：`transformer_lab/`，不修改 backend / frontend / database 业务代码。
- 模块划分：`src/torch_basics`（Tensor 基础）、`src/data`（数据管线）、`src/attention`（注意力）、`src/model`（Encoder/回归）、`src/training`（训练）、`src/evaluation`（评价）、`src/inference`（前向预测）、`src/optimization`（后向搜索）。

## 当前模型设计

- 目标：Transformer 回归模型，前向预测 + 后向工艺参数优化。
- 数据流：特征行 → Tensor → 标准化 → 注意力 → Encoder → 回归头 → 训练/评价 → 前向预测 → 后向搜索。

## 数据管线

- `X_` 字段 = 输入特征；`y_` 字段 = 预测目标；`meta_` 字段 = 追踪/分组，不作模型输入。
- 关注 `sequence_id` 与 `meta_leak_group`，避免同一实验链被拆进训练/测试集。
- 标准化参数只从训练集拟合。

## 关键代码

- `src/torch_basics/tensors.py`：`rows_to_tensor`（特征行 → 2D Tensor，含行宽检查），测试通过。

## 训练结果

（暂无，尚未开始训练）

## 遇到的问题

（暂无）

## 下一步计划

1. 补标准化函数（fit / apply 分离）。
2. 确认真实 ALE 数据字段定义。
3. 编写 `src/data/dataset.py` 读取数据、构建 X/y。

## 待办 / 疑问

（暂无）
