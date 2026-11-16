# 下次续课（NEXT_SESSION）

> 这是下次开课的首要续接文件。每次结束课程必须更新本文件。

## 当前任务

- 模块：M01 数据管线
- 任务：M01-T002 按组整组划分 train/val/test（READY）

## 上次完成了什么

- 建立长期教学规则（改为 AI 编写代码、学习者验收）。
- 建立 management 目录及 7 份管理文件。
- 完成并验收：M01-T001（合成数据）、M02-T001（标准化）、M03-T001（评价指标）。

## 当前正在开发哪个文件

- `src/data/dataset.py`（补 `split_by_group` 函数）

## 下一次具体要完成什么

1. 实现 `split_by_group`（按组整组划分，防泄漏）。
2. 测试三集合组号无交集、行数之和=总数。
3. 验收后进入 M01-T003（真实数据读取）。

## 需要准备的数据和环境

- 环境已就绪：Python 3.12.10 / torch 2.12.1+cpu / numpy 2.5.0 / pandas 3.0.3。
- 真实 ALE 数据接入前需先核实字段（X_/y_/meta_/sequence_id/meta_leak_group）。

## 下次打开 VS Code 后的第一条开发任务

读取 management/PROJECT_STATE.json 与 TASKS.md，从 M01-T002（split_by_group）继续。

## 不需要重复学习的内容

- Tensor 基础、标准化、评价指标、合成数据生成均已验收。

