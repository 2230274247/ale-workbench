# transformer_lab

ALE Workbench 旁边的独立学习工程。目标是亲手写成一个 PyTorch Transformer 回归模型：前向预测材料工艺结果，再在约束内搜索工艺参数。

本目录的 Python 文件初始是空位。算法由学习者自己敲入，不从业务代码里复制。

## 模块

| 路径 | 职责 |
|---|---|
| `src/torch_basics/tensors.py` | 把特征行变成 Tensor |
| `src/data/dataset.py` | 批次与以后的 ALE 表格读取 |
| `src/attention/scaled_dot_product.py` | 缩放点积注意力 |
| `src/attention/multi_head.py` | 多头注意力 |
| `src/model/encoder.py` | Transformer Encoder |
| `src/model/regressor.py` | 回归模型 |
| `src/training/loop.py` | 训练一步 |
| `src/evaluation/metrics.py` | MAE、RMSE、R² |
| `src/inference/forward.py` | 加载模型并预测 |
| `src/optimization/search.py` | 约束内的后向参数搜索 |

数据流：特征行 → Tensor → 注意力 → Encoder → 回归头 → 训练与评价 → 前向预测 → 后向搜索。

## 运行

在 `transformer_lab` 目录中执行模块，例如以后写完第一段时：

```powershell
python -m src.torch_basics.tensors
```

不要把 PyTorch 安装进 `backend\.venv-win`。那个环境服务于现有工作台。学习依赖若要安装，使用本目录单独的虚拟环境，并先经学习者同意。

## 数据

形状验证只用合成数字。真实实验表接入前要单独确认导出文件和隔离方式。这里不连接生产数据库。
