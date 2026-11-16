# 测试报告（TEST_REPORT）

> 记录每个模块和批次的真实测试结果。只记录实际运行过的测试。

## M01 数据管线

### M01-T001 合成数据生成器
- 命令：`python -m src.data.dataset`
- 结果：PASS
- 输出：`X shape: torch.Size([180, 8])`、`y shape: torch.Size([180])`、`groups: [0, 0, 0, 1, 1, 1] ...`

## M02 特征工程

### M02-T001 数值标准化
- 命令：`python -m src.torch_basics.tensors`
- 结果：PASS
- 输出：`mean: [2.5, 3.5, 4.5]`、`std: [1.5, 1.5, 1.5]`、标准化后 `[[-1,-1,-1],[1,1,1]]`

## M03 传统模型基线

### M03-T001 评价指标
- 命令：`python -m src.evaluation.metrics`
- 结果：PASS
- 输出：`MAE: 0.25`、`RMSE: 0.3535533845424652`、`R2: 0.976190447807312`
