# 架构（ARCHITECTURE）

## 模块结构

```
transformer_lab/src/
├── torch_basics/     # Tensor 基础工具（rows_to_tensor、标准化）
├── data/             # 数据管线（合成数据、分组划分、真实数据读取）
├── features/         # 特征工程（选择、编码、标准化、目标构建、预处理器保存）
├── model/            # 模型（Embedding、Attention、MHA、FFN、Residual、LayerNorm、Encoder、回归头）
├── training/         # 训练（Dataset、DataLoader、Optimizer、Loss、单轮训练、验证、EarlyStopping、Checkpoint）
├── evaluation/       # 评价（MAE、RMSE、R²）
├── inference/        # 前向预测（加载模型、预测）
└── optimization/     # 后向参数搜索
```

## 数据流

```
真实/合成数据 → 字段检查 → 缺失值处理 → 特征选择 → 类别编码 → 数值标准化
→ 目标构建 → 分组划分(train/val/test) → Dataset/DataLoader
→ 模型(Embedding→Attention→MHA→FFN→Residual→LayerNorm→Encoder→回归头)
→ Loss → Optimizer → 训练/验证 → 评价(R²/MAE/RMSE) → 保存(权重+预处理参数)
→ 前向预测 → 后向参数搜索 → FastAPI → ALE Workbench
```

## 模块依赖

- `evaluation` 无依赖，最先完成。
- `torch_basics` 无依赖。
- `data` 依赖 `torch_basics`（标准化）。
- `features` 依赖 `data`。
- `model` 依赖 `torch_basics`。
- `training` 依赖 `data`、`model`、`evaluation`。
- `inference` 依赖 `model`、`features`。
- `optimization` 依赖 `inference`。

## 接口约定

- 所有 Tensor 默认 `dtype=torch.float32`。
- X 形状：`(batch, n_features)`；进入 Transformer 前扩展为 `(batch, seq_len, d_model)`。
- y 形状：`(batch,)` 或 `(batch, 1)`。
- 标准化参数（mean/std）只从训练集拟合，验证/测试只 apply。
- 模型权重与预处理参数一起保存，训练和预测用完全一致的特征处理。
