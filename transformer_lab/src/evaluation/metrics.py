import torch


def mae(y_true, y_pred):
    """平均绝对误差。"""
    return (y_true - y_pred).abs().mean().item()


def rmse(y_true, y_pred):
    """均方根误差。"""
    return torch.sqrt(((y_true - y_pred) ** 2).mean()).item()


def r2(y_true, y_pred):
    """决定系数 R²。"""
    ss_res = ((y_true - y_pred) ** 2).sum()
    ss_tot = ((y_true - y_true.mean()) ** 2).sum()
    return (1 - ss_res / ss_tot).item()


if __name__ == "__main__":
    y_true = torch.tensor([3.0, 5.0, 2.0, 8.0])
    y_pred = torch.tensor([2.5, 5.0, 2.0, 7.5])
    print("MAE:", mae(y_true, y_pred))
    print("RMSE:", rmse(y_true, y_pred))
    print("R2:", r2(y_true, y_pred))