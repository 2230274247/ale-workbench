# 学习进度

> 记录完成的代码、运行结果、掌握程度与下一步计划。
> 状态区分：`计划` / `代码已写` / `测试通过` / `训练成功`，不能把计划当作完成。

## 环境

- Python 3.12.10
- torch 2.12.1+cpu
- numpy 2.5.0
- pandas 3.0.3

## 当前阶段

M01 数据管线（进行中）

## 已完成功能（已验收）

### M01-T001 合成数据生成器（ACCEPTED）
- `src/data/dataset.py`：`make_synthetic_data`，输出 X(180,8)/y(180)/groups。
- 测试：`python -m src.data.dataset` → PASS。

### M02-T001 数值标准化（ACCEPTED）
- `src/torch_basics/tensors.py`：`fit_standardizer` / `apply_standardizer`，fit/apply 分离防泄漏。

### M03-T001 评价指标（ACCEPTED）
- `src/evaluation/metrics.py`：`mae` / `rmse` / `r2`。

## 尚未完成

- M01-T002：`split_by_group` 按组整组划分（READY）。
- M01-T003：真实数据读取。
- 其余 M02~M08 全部任务。

## 已掌握

- Tensor 基础、标准化、评价指标、合成数据生成、防泄漏分组划分原理。

## 遇到的问题

（暂无）

## 遗留问题

（暂无）
