# ALE + AI 学习进度（Cursor 与 ChatGPT 共用）

> 只记录学习者亲手写过、并且实际运行过的代码。导师讲解不算掌握。不要写入生产秘密或真实实验数据。

## 总览
- 当前单元：T0 · 特征行变成 Tensor
- 当前文件：`transformer_lab/src/torch_basics/tensors.py`（仍是占位注释，函数尚未由学习者输入）
- 学习方式：聊天展示 5～15 行，学习者亲手输入、运行、再继续
- 当前状态：工程骨架已建好，第一段代码尚未开始敲
- 最近一次学习：2026-11-13 切换为结对编程
- 本地项目版本：只读所见 HEAD `9686c61`；工作区另有未提交业务改动，保持不动
- 安全边界：不修改业务模块、生产库和原件；不把 PyTorch 装进 `backend\.venv-win`

## 能力地图（0=未接触，1=能跟着敲并跑通，2=能独立改，3=能解释并接到下一模块）
| 能力 | 等级 | 验证证据 | 下次动作 |
|---|---:|---|---|
| Tensor 特征批次 | 0 | 文件仍是占位注释 | 亲手输入 `feature_batch` |
| 数据批次 | 0 | 未写 | T1 |
| Scaled Dot-Product Attention | 0 | 未写 | T2 |
| Multi-Head Attention | 0 | 未写 | T3 |
| Encoder / 回归模型 | 0 | 未写 | T4–T5 |
| 训练与评价 | 0 | 未写 | T6–T7 |
| 前向预测与后向搜索 | 0 | 未写 | T8–T9 |

## 已完成的代码
- 函数和类：无
- 成功运行：无
- 已理解的原理：尚无运行证据。此前能抄出宽表三个 Y 列名，那是旧的阅读课，不记入本工程进度

## 还需要补充
- 当前使用的 `backend\.venv-win` 里没有 `torch`（2026-11-13 实际 import 失败：`ModuleNotFoundError`）
- 第一段代码跑通之前，不要安装到后端虚拟环境

## 下一段要写的代码
`feature_batch(rows)`：把合成特征行变成形状 `(batch, n_features)`、dtype 为 `float32` 的 Tensor。

## 任务记录
### 旧模式（保留，不作为 Transformer 工程进度）
- 打开过 `backend/app/quick_dataset.py`，讲解后抄对 `y_loss_nm`、`y_epc_a_per_cycle`、`y_uniformity_pct`
- `sequence_id` 分组题未答。该模式已停用

### 2026-11-13 切换结对编程
- 学习者要求改为亲手写 `transformer_lab`
- 已创建空目录、占位 Python 文件、README，并改写课程规则与三份学习文档
- 未写入任何算法，未改业务代码，未安装依赖
