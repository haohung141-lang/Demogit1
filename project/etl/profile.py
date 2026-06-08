# project/etl/profile.py
# - Duyệt qua các DataFrame đã được extract từ Excel.
# - In ra số dòng và số cột của từng bảng dữ liệu.
# - Kiểm tra danh sách cột và kiểu dữ liệu.
# - Kiểm tra giá trị thiếu/null nếu có.
# - Hỗ trợ đánh giá chất lượng dữ liệu trước khi transform.
# - hiểu cấu trúc dữ liệu nguồn trước khi nạp vào Data Warehouse.

import pandas as pd
import numpy as np

def profile_dataframe(df: pd.DataFrame, name: str) -> dict:
    """
    Profile cơ bản: shape, dtypes, missing, duplicates.
    """
    result = {
        "table_name": name,
        "row_count": int(df.shape[0]),
        "col_count": int(df.shape[1]),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "missing_count": {c: int(df[c].isna().sum()) for c in df.columns},
        "duplicate_rows": int(df.duplicated().sum()),
    }
    return result

def detect_basic_outliers(df: pd.DataFrame, numeric_cols: list) -> dict:
    """
    Phát hiện outlier đơn giản bằng IQR.
    """
    outliers = {}
    for col in numeric_cols:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            outliers[col] = 0
            continue
        q1 = s.quantile(0.25)
        q3 = s.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers[col] = int(((s < lower) | (s > upper)).sum())
    return outliers

def profile_all(data: dict) -> dict:
    report = {}
    for name, df in data.items():
        report[name] = profile_dataframe(df, name)
    return report