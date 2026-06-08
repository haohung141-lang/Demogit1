# project/etl/transform.py
# - Nhận dữ liệu đã extract từ Excel dưới dạng pandas DataFrame.
# - Chuẩn hóa tên cột, kiểu dữ liệu ngày tháng và kiểu số.
# - Làm sạch dữ liệu thiếu/null nếu cần.
# - Tạo các cột mới phục vụ phân tích nhân sự:
#   + Is_Exit_Flag: xác định nhân viên đã nghỉ việc hay chưa.
#   + Tenure_Months: tính số tháng làm việc của nhân viên.
#   + Salary_Band: phân nhóm mức lương.
# - Chuyển bảng role_kpis sang dạng long format để chuẩn hóa dữ liệu KPI.
# - Tạo bảng dim_date phục vụ phân tích theo thời gian.
# - Trả về dữ liệu đã xử lý để load vào staging và xây dựng Data Warehouse.

import pandas as pd
import numpy as np
from datetime import datetime


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chuẩn hóa tên cột: giữ nguyên chữ cái, thay khoảng trắng bằng _, strip.
    """
    df = df.copy()
    df.columns = [c.strip().replace(" ", "_") for c in df.columns]
    return df


def parse_dates(df: pd.DataFrame, date_cols: list) -> pd.DataFrame:
    """
    Chuyển các cột ngày tháng về kiểu datetime.
    Dữ liệu ngày trong file đang dạng Việt Nam dd/mm/yyyy nên dùng dayfirst=True.
    """
    df = df.copy()
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce",
                dayfirst=True
            )
    return df


def standardize_text_columns(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """
    Chuẩn hóa các cột text:
    - Ép kiểu string
    - Xóa khoảng trắng đầu/cuối
    - Chuyển chuỗi nan/None thành missing value
    """
    df = df.copy()
    for col in cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype("string")
                .str.strip()
                .replace({"nan": pd.NA, "None": pd.NA})
            )
    return df


def create_salary_band(
    df: pd.DataFrame,
    salary_col: str = "Base_Salary_Annual"
) -> pd.DataFrame:
    df = df.copy()

    if salary_col not in df.columns:
        return df

    # Ép lương năm về numeric để tránh lỗi khi dữ liệu bị đọc dạng text
    df[salary_col] = pd.to_numeric(
        df[salary_col],
        errors="coerce"
    )

    # Tính lương tháng tạm thời để phân nhóm
    monthly_salary = df[salary_col] / 12

    bins = [
        -np.inf,
        10_000_000,
        20_000_000,
        30_000_000,
        40_000_000,
        np.inf
    ]

    labels = [
        "<10 triệu/tháng",
        "10-20 triệu/tháng",
        "20-30 triệu/tháng",
        "30-40 triệu/tháng",
        ">40 triệu/tháng"
    ]

    df["Salary_Band"] = pd.cut(
        monthly_salary,
        bins=bins,
        labels=labels,
        right=False
    )

    # Nếu lương bị null thì gán nhãn riêng
    df["Salary_Band"] = df["Salary_Band"].astype("string")
    df["Salary_Band"] = df["Salary_Band"].fillna("Không xác định")

    return df


def transform_employees(
    df: pd.DataFrame,
    max_data_month: pd.Timestamp = None
) -> pd.DataFrame:
    """
    Transform bảng employees:
    - Chuẩn hóa tên cột
    - Parse Hire_Date, Exit_Date
    - Chuẩn hóa text
    - Xử lý trùng Employee_Id
    - Tạo Is_Exit_Flag
    - Tính Tenure_Months
    - Tạo Salary_Band theo dữ liệu lương VND/năm
    """

    df = normalize_column_names(df)

    df = parse_dates(df, ["Hire_Date", "Exit_Date"])

    df = standardize_text_columns(
        df,
        [
            "Employee_Id",
            "Full_Name",
            "Education_Level",
            "Department",
            "Job_Role",
            "Job_Level",
            "Employment_Type",
            "Store_Location",
            "Store_Id",
            "Manager_Id",
            "Manager_Name",
            "Manager_Status"
        ]
    )

    # Chuẩn hóa kiểu số
    numeric_cols = [
        "Age",
        "Base_Salary_Annual",
        "Store_Location_Latitude",
        "Store_Location_Longitude"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    # Xử lý trùng Employee_Id: giữ bản ghi cuối cùng theo Hire_Date
    if "Employee_Id" in df.columns and "Hire_Date" in df.columns:
        df = (
            df
            .sort_values(["Employee_Id", "Hire_Date"])
            .drop_duplicates(subset=["Employee_Id"], keep="last")
        )

    # Tạo biến đánh dấu nghỉ việc
    df["Is_Exit_Flag"] = df["Exit_Date"].notna().astype(int)

    # Tính Tenure_Months tới tháng cuối dữ liệu nếu có, nếu không dùng ngày hiện tại
    if max_data_month is None:
        ref_date = pd.Timestamp.today().normalize()
    else:
        ref_date = pd.to_datetime(max_data_month)

    end_for_tenure = df["Exit_Date"].fillna(ref_date)

    df["Tenure_Months"] = (
        (end_for_tenure.dt.year - df["Hire_Date"].dt.year) * 12
        + (end_for_tenure.dt.month - df["Hire_Date"].dt.month)
    ).clip(lower=0)

    # Tạo Salary_Band mới theo VND/năm
    df = create_salary_band(df, "Base_Salary_Annual")

    # Chuẩn hóa một số danh mục nếu dữ liệu có tiếng Anh lẫn tiếng Việt
    replacements = {
        "Employment_Type": {
            "Full-time": "Toàn thời gian",
            "Part-time": "Bán thời gian",
            "Seasonal": "Thời vụ",
            "Contractor": "Hợp đồng",
            "Toàn thời gian": "Toàn thời gian",
            "Bán thời gian": "Bán thời gian",
            "Thời vụ": "Thời vụ",
            "Hợp đồng": "Hợp đồng"
        }
    }

    for col, mapping in replacements.items():
        if col in df.columns:
            df[col] = df[col].replace(mapping)

    return df


def transform_stores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform bảng stores.
    """
    df = normalize_column_names(df)

    df = parse_dates(df, ["Opening_Date"])

    df = standardize_text_columns(
        df,
        [
            "Store_Id",
            "Store_Name",
            "City",
            "Store_Type"
        ]
    )

    numeric_cols = [
        "City_Latitude",
        "City_Longitude"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    if "Store_Id" in df.columns:
        df = df.drop_duplicates(subset=["Store_Id"], keep="last")

    return df


def transform_monthly_performance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform bảng monthly_performance:
    - Chuẩn hóa tên cột
    - Chuẩn hóa Employee_Id, Year_Month
    - Tạo Month_Start_Date
    - Ép kiểu số cho các chỉ số
    - Xử lý trùng Employee_Id + Year_Month
    """

    df = normalize_column_names(df)

    df = standardize_text_columns(
        df,
        [
            "Employee_Id",
            "Year_Month"
        ]
    )

    # Chuyển Year_Month về ngày đầu tháng
    if "Year_Month" in df.columns:
        df["Month_Start_Date"] = pd.to_datetime(
            df["Year_Month"].astype("string") + "-01",
            errors="coerce"
        )

    # Bool / flag -> int
    for col in ["Promotion_Flag", "Salary_Increase_Flag"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            ).fillna(0).astype(int)

    numeric_cols = [
        "Performance_Rating",
        "Training_Hours",
        "Overtime_Hours",
        "Absenteeism_Days",
        "Monthly_Bonus",
        "Benefits_Cost",
        "Employee_Satisfaction",
        "Engagement_Index",
        "Manager_Evaluation"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    # Loại trùng khóa logic
    if "Employee_Id" in df.columns and "Year_Month" in df.columns:
        df = df.drop_duplicates(
            subset=["Employee_Id", "Year_Month"],
            keep="last"
        )

    return df


def transform_role_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform bảng role_kpis:
    - Chuẩn hóa text
    - Tạo Month_Start_Date
    - Unpivot 3 cặp KPI từ wide sang long
    """

    df = normalize_column_names(df)

    df = standardize_text_columns(
        df,
        [
            "Employee_Id",
            "Year_Month",
            "Kpi_1_Name",
            "Kpi_2_Name",
            "Kpi_3_Name"
        ]
    )

    if "Year_Month" in df.columns:
        df["Month_Start_Date"] = pd.to_datetime(
            df["Year_Month"].astype("string") + "-01",
            errors="coerce"
        )

    # Ép các cột KPI về số
    for col in [
        "Kpi_1_Value",
        "Kpi_2_Value",
        "Kpi_3_Value",
        "Productivity_Index"
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    # Unpivot 3 KPI pairs -> long
    rows = []

    for _, r in df.iterrows():
        for idx in [1, 2, 3]:
            kpi_name_col = f"Kpi_{idx}_Name"
            kpi_value_col = f"Kpi_{idx}_Value"

            if kpi_name_col in df.columns and kpi_value_col in df.columns:
                rows.append({
                    "Employee_Id": r.get("Employee_Id"),
                    "Year_Month": r.get("Year_Month"),
                    "Month_Start_Date": r.get("Month_Start_Date"),
                    "Kpi_Name": r.get(kpi_name_col),
                    "Kpi_Value": r.get(kpi_value_col),
                    "Productivity_Index": r.get("Productivity_Index"),
                })

    long_df = pd.DataFrame(rows)

    if not long_df.empty:
        long_df = long_df.drop_duplicates(
            subset=["Employee_Id", "Year_Month", "Kpi_Name"],
            keep="last"
        )

    return long_df


def transform_business_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform bảng business_outcomes:
    - Chuẩn hóa text
    - Tạo Month_Start_Date
    - Ép kiểu số
    - Loại trùng Store_Id + Department + Year_Month
    """

    df = normalize_column_names(df)

    df = standardize_text_columns(
        df,
        [
            "Store_Id",
            "Department",
            "Year_Month"
        ]
    )

    if "Year_Month" in df.columns:
        df["Month_Start_Date"] = pd.to_datetime(
            df["Year_Month"].astype("string") + "-01",
            errors="coerce"
        )

    numeric_cols = [
        "Sales_Target",
        "Sales_Actual",
        "Customer_Satisfaction",
        "Nps_Score",
        "Waste_Percentage",
        "On_Time_Delivery"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    if all(col in df.columns for col in ["Store_Id", "Department", "Year_Month"]):
        df = df.drop_duplicates(
            subset=["Store_Id", "Department", "Year_Month"],
            keep="last"
        )

    return df


def build_dim_date(
    employees_df,
    stores_df,
    monthly_df,
    role_kpis_long_df,
    business_df
) -> pd.DataFrame:
    """
    Tạo bảng dim_date theo ngày.
    Lấy range ngày từ Hire_Date, Exit_Date, Opening_Date và Month_Start_Date.
    """

    date_series = []

    for c in ["Hire_Date", "Exit_Date"]:
        if c in employees_df.columns:
            date_series.append(employees_df[c].dropna())

    if "Opening_Date" in stores_df.columns:
        date_series.append(stores_df["Opening_Date"].dropna())

    for temp_df in [monthly_df, role_kpis_long_df, business_df]:
        if "Month_Start_Date" in temp_df.columns:
            date_series.append(temp_df["Month_Start_Date"].dropna())

    if not date_series:
        return pd.DataFrame(
            columns=[
                "FullDate",
                "DateKey",
                "Year",
                "Quarter",
                "Month",
                "MonthName",
                "YearMonth",
                "MonthStartDate",
                "MonthEndDate"
            ]
        )

    all_dates = (
        pd.concat(date_series, ignore_index=True)
        .dropna()
        .drop_duplicates()
    )

    min_date = all_dates.min().normalize()
    max_date = all_dates.max().normalize()

    dim_date = pd.DataFrame({
        "FullDate": pd.date_range(min_date, max_date, freq="D")
    })

    dim_date["DateKey"] = dim_date["FullDate"].dt.strftime("%Y%m%d").astype(int)
    dim_date["Year"] = dim_date["FullDate"].dt.year
    dim_date["Quarter"] = dim_date["FullDate"].dt.quarter
    dim_date["Month"] = dim_date["FullDate"].dt.month

    # Đổi sang tiếng Việt để hiển thị Power BI đẹp hơn
    dim_date["MonthName"] = "Tháng " + dim_date["Month"].astype(str)

    dim_date["YearMonth"] = dim_date["FullDate"].dt.strftime("%Y-%m")
    dim_date["MonthStartDate"] = dim_date["FullDate"].values.astype("datetime64[M]")
    dim_date["MonthEndDate"] = dim_date["MonthStartDate"] + pd.offsets.MonthEnd(0)

    return dim_date


def transform_all(data: dict) -> dict:
    """
    Hàm transform toàn bộ dữ liệu.
    """

    raw_monthly = transform_monthly_performance(
        data["monthly_performance"]
    )

    max_month = raw_monthly["Month_Start_Date"].max()

    employees = transform_employees(
        data["employees"],
        max_data_month=max_month
    )

    stores = transform_stores(
        data["stores"]
    )

    monthly = raw_monthly

    role_kpis_long = transform_role_kpis(
        data["role_kpis"]
    )

    business = transform_business_outcomes(
        data["business_outcomes"]
    )

    dim_date = build_dim_date(
        employees,
        stores,
        monthly,
        role_kpis_long,
        business
    )

    return {
        "employees": employees,
        "stores": stores,
        "monthly_performance": monthly,
        "role_kpis_long": role_kpis_long,
        "business_outcomes": business,
        "dim_date": dim_date,
        "data_dictionary": normalize_column_names(data["Data_Dictionary"])
    }