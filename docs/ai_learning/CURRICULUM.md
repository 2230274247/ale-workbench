# ALE Transformer 实战课程（结对编程）

## 1. 目标
学习者亲手在 `transformer_lab/` 写出一个可训练、可加载、可做前向预测的 Transformer 回归模型，并在约束内用它搜索工艺参数。最终接入 ALE Workbench 前，必须另得明确授权。实现使用 PyTorch。本课程里的 Transformer 不是 TensorFlow。

代码由学习者在编辑器里输入。导师只在聊天中展示大约 5～15 行，并解释语法、shape、数学和模块之间的连接。

## 2. 教学顺序
顺序可以按掌握情况调整。每一段都留在同一工程里，不写学完就丢的演示。

| 阶段 | 目录 | 要长出来的能力 |
|---|---|---|
| T0 | `src/torch_basics/tensors.py` | 特征行变成 `(batch, n_features)` Tensor |
| T1 | `src/data/dataset.py` | 合成批次、以后换成 ALE 导出表 |
| T2 | `src/attention/scaled_dot_product.py` | 缩放点积注意力 |
| T3 | `src/attention/multi_head.py` | 多头注意力，调用 T2 |
| T4 | `src/model/encoder.py` | Encoder 块：注意力、残差、归一化、前馈 |
| T5 | `src/model/regressor.py` | 表格特征进 Encoder，回归头输出多目标 |
| T6 | `src/training/loop.py` | 损失、反向传播、优化器一步 |
| T7 | `src/evaluation/metrics.py` | MAE、RMSE、R²，按材料分开 |
| T8 | `src/inference/forward.py` | 加载权重并做前向预测 |
| T9 | `src/optimization/search.py` | 在工艺约束内调用前向模型搜索参数 |

进入真实 ALE 数据之前，先用合成小表把 shape 跑通。训练、验证、测试必须分开。预处理只在训练集上拟合。连续实验按 `sequence_id` 整组划分。

## 3. 安全边界
- 不修改 `backend/`、`frontend/`、`database/`、`storage/` 里的业务实现，除非学习者明确授权。
- 不写生产库，不读取密钥和实验原件。
- 不自动安装依赖、不自动训练。
- `AGENTS.md` 与 `docs/P0_数据安全基线.md` 优先于本课程文档。

## 4. 进度与交接
实际写过并运行过的代码记入 `PROGRESS.md`。讲解本身不算掌握。学习者说「同步 ChatGPT」时更新 `HANDOFF_TO_CHATGPT.md`，由学习者手动复制。

## 5. 科学性检查
- 原始记录、派生标签、模型特征分开，并保留单位。
- 不以测试集选模型，不在全数据上拟合标准化器。
- 比较模型时使用相同任务、划分和指标。保留失败结果。
- 样本不足时先做线性或岭回归基线，再增加 Transformer。
- 记录种子、超参数、软件版本和权重位置。
