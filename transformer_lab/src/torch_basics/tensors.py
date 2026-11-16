# 待编写：特征行 -> Tensor。算法由学习者亲手输入。
#数据维度：数据不是一行行表格，而是一块块数字矩阵，一条ALE数据最终会变成（batch，seq_len, d_model）的三维张量
#其中，batch：一次喂给模型多少条样本；seq_len：每条样本的长度；d_model：每条样本的特征维度

import torch

def rows_to_tensor(rows):
    """长度匹配检查：确保所有行的长度一致。"""
    if len(rows) == 0:
        raise ValueError("输入的特征行列表不能为空。")
    width = len(rows[0])
    for i, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"第{i}行的长度{len(row)}与第0行长度{width}不一致。")

    """把若干特征行（每行是等长的数字列表）转化成一个2D Tensor。"""
    """torch.tensor(...)：把 Python 列表转成 Tensor。"""
    """rows：输入，例如 [[1.0, 2.0], [3.0, 4.0]]。"""
    """dtype=torch.float32：指定 Tensor 的数据类型为 32 位浮点数。"""
    return torch.tensor(rows, dtype=torch.float32)  

def fit_standardizer(tensor):
    """从训练数据拟合标准化参数：返回每列的均值与标准差。"""
    mean = tensor.mean(dim=0)
    std = tensor.std(dim=0, unbiased=False)
    return mean, std


def apply_standardizer(tensor, mean, std):
    """用已拟合的均值/标准差对数据做标准化。"""
    return (tensor - mean) / std


if __name__ == "__main__":
    sample = [[1.0,2.0,3.0], [4.0,5.0,6.0]]
    t = rows_to_tensor(sample)
    print(t)
    print("shape:",t.shape)  # 输出 Tensor 的形状
    mean, std = fit_standardizer(t)
    print("mean:", mean)
    print("std:", std)
    print("标准化后的数据:", apply_standardizer(t, mean, std))