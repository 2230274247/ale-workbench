import torch


def make_synthetic_data(n_groups=60, rows_per_group=3, n_features=8, seed=0):
    """生成合成 ALE 数据：每组代表一条实验链，组内共享一个隐藏因子。

    返回 (X, y, groups)，其中 groups 是每行所属的组号，用于防泄漏划分。
    """
    g = torch.Generator().manual_seed(seed)
    X_list, y_list, groups = [], [], []
    for group_id in range(n_groups):
        # 每个组一个隐藏因子，组内所有行共享，模拟同一实验链的相关性
        hidden = torch.randn(1, generator=g)
        for _ in range(rows_per_group):
            x = torch.randn(n_features, generator=g) + hidden
            y = x.sum() * 0.5 + hidden * 2.0 + torch.randn(1, generator=g) * 0.1
            X_list.append(x)
            y_list.append(y)
            groups.append(group_id)
    X = torch.stack(X_list)
    y = torch.stack(y_list).squeeze(-1)
    return X, y, torch.tensor(groups)


if __name__ == "__main__":
    X, y, groups = make_synthetic_data()
    print("X shape:", X.shape)
    print("y shape:", y.shape)
    print("groups:", groups[:6].tolist(), "...")