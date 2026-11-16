# Cursor → ChatGPT 课程交接卡

> 学习者说「同步 ChatGPT」时更新本文件，再手动复制到 ChatGPT。不会自动发送。不要写入凭据或真实实验数据。

## 当前状态
- 项目：ALE Workbench 旁的 `transformer_lab/`（本地 `H:\ALE_AI`）
- 教学目标：亲手用 PyTorch 写成 Transformer 回归模型，再做受约束的后向工艺搜索
- 教学方式：聊天里每次约 5～15 行，学习者自己敲。导师不代写 Python 算法
- 当前文件：`transformer_lab/src/torch_basics/tensors.py`（只有占位注释）
- 已亲手完成的函数或类：无
- 已成功运行：无
- 已理解并有运行证据的原理：无
- 已知环境事实：`backend\.venv-win` 中 `import torch` 失败，不要把 PyTorch 装进这个环境
- 下一步：学习者把 `feature_batch` 敲进 `tensors.py`，再运行 `python -m src.torch_basics.tensors`

## 希望 ChatGPT 协助
按结对编程继续：指定文件、给一小段可复用代码、解释 shape 和语法，然后等待学习者自己输入。不要生成整个模型，不要修改 ALE 业务代码。

## 安全
生产数据库、原始实验文件和密钥不在本交接范围内。
