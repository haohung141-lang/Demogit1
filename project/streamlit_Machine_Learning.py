# streamlit_app.py
# -*- coding: utf-8 -*-

"""
HR Analytics - Dự đoán nguy cơ nghỉ việc nhân viên

Bản viết lại theo yêu cầu:
1) Nạp dữ liệu trực tiếp từ SQL Server, không import Excel.
2) Dự đoán nhân viên mới và giải thích từng dự đoán bằng SHAP.
3) Dự đoán toàn bộ nhân viên trong dữ liệu DWH/STG và có SHAP cho từng nhân viên được chọn.
4) Biểu đồ đẹp: mất cân bằng nhãn, confusion matrix, threshold tuning, error analysis, feature importance, phân bố rủi ro.
"""

import os
import sys
import urllib
import warnings
from datetime import date

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split, StratifiedKFold, RandomizedSearchCV, cross_validate
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, average_precision_score, confusion_matrix,
    classification_report,
)

warnings.filterwarnings("ignore")
os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import shap
    SHAP_AVAILABLE = True
except Exception:
    SHAP_AVAILABLE = False

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(page_title="HR Analytics - ML nghỉ việc", page_icon="📊", layout="wide")
st.markdown(
    """
    <style>
    .main-title {font-size: 34px; font-weight: 800; color: #1F4E79; margin-bottom: 0px;}
    .sub-title {font-size: 16px; color: #555; margin-top: 0px; margin-bottom: 20px;}
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown('<div class="main-title">HR Analytics - Dự đoán nguy cơ nghỉ việc nhân viên</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Nạp dữ liệu từ SQL Server, huấn luyện mô hình, dự đoán nhân viên mới, dự đoán nhân viên trong DWH và giải thích bằng SHAP.</div>', unsafe_allow_html=True)

# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("1. Cấu hình SQL Server")
server = st.sidebar.text_input("SQL Server", value=r"HUYLEE\SQLEXPRESS")
database = st.sidebar.text_input("Database", value="HRAnalyticsDW")
driver = st.sidebar.selectbox("ODBC Driver", ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"], index=0)

st.sidebar.header("2. Cấu hình dữ liệu KPI")
prediction_date = st.sidebar.date_input("Ngày dự đoán", value=date.today())
lookback_months = st.sidebar.slider("Số tháng KPI dùng để tổng hợp", 3, 36, 12, 3)
use_lookback = st.sidebar.checkbox("Lọc KPI trước ngày dự đoán bằng Month_Start_Date", value=True)

st.sidebar.header("3. Cấu hình mô hình")
model_name = st.sidebar.selectbox(
    "Chọn mô hình",
    ["Logistic Regression", "Decision Tree", "Random Forest", "Extra Trees", "Gradient Boosting"],
    index=2,
)
test_size = st.sidebar.slider("Tỷ lệ tập test", 0.1, 0.4, 0.2, 0.05)
threshold = st.sidebar.slider("Ngưỡng dự đoán nghỉ việc", 0.1, 0.9, 0.4, 0.05)
use_tuning = st.sidebar.checkbox("Tối ưu tham số bằng RandomizedSearchCV", value=False)
# ============================================================
# CONSTANTS
# ============================================================

BASE_FEATURE_COLS = [
    "Age", "Base_Salary_Annual", "Tenure_Months_As_Of",
    "Avg_Performance_Rating", "Avg_Training_Hours", "Avg_Overtime_Hours",
    "Avg_Absenteeism_Days", "Avg_Employee_Satisfaction", "Avg_Engagement_Index",
    "Avg_Manager_Evaluation", "Promotion_Rate", "Salary_Increase_Rate",
    "Avg_Monthly_Bonus", "Avg_Benefits_Cost",
]
ENGINEERED_FEATURE_COLS = [
    "Salary_Per_Tenure", "Overtime_Training_Ratio", "Absence_Per_Tenure",
    "Satisfaction_Engagement_Mean", "Performance_Manager_Gap",
    "Workload_Risk_Index", "Development_Index",
]
ALL_FEATURE_COLS = BASE_FEATURE_COLS + ENGINEERED_FEATURE_COLS

REQUIRED_EMPLOYEE_COLS = ["Employee_Id", "Age", "Hire_Date", "Base_Salary_Annual", "Is_Exit_Flag"]
REQUIRED_MONTHLY_COLS = [
    "Employee_Id", "Performance_Rating", "Training_Hours", "Overtime_Hours",
    "Absenteeism_Days", "Employee_Satisfaction", "Engagement_Index", "Manager_Evaluation",
]

# ============================================================
# SQL HELPERS
# ============================================================

def create_sql_engine(server_name: str, db_name: str, driver_name: str):
    params = urllib.parse.quote_plus(
        f"DRIVER={{{driver_name}}};SERVER={server_name};DATABASE={db_name};"
        "Trusted_Connection=yes;TrustServerCertificate=yes;"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def get_table_columns(engine, schema_name: str, table_name: str):
    q = f"""
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{schema_name}' AND TABLE_NAME = '{table_name}'
    ORDER BY ORDINAL_POSITION
    """
    try:
        return pd.read_sql(q, con=engine)["COLUMN_NAME"].tolist()
    except Exception:
        return []


def check_required(columns: list, required: list, table_label: str):
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValueError(f"Bảng {table_label} thiếu cột bắt buộc: {', '.join(missing)}")


def optional_avg_expr(cols: list, source_col: str, output_alias: str):
    if source_col in cols:
        return f"AVG(TRY_CAST(mp.[{source_col}] AS FLOAT)) AS [{output_alias}]"
    return f"CAST(NULL AS FLOAT) AS [{output_alias}]"


@st.cache_data(show_spinner=False)
def load_data_from_sql(server_name, db_name, driver_name, prediction_date_str, lookback_months_value, enable_lookback):
    engine = create_sql_engine(server_name, db_name, driver_name)

    emp_cols = get_table_columns(engine, "stg", "employees")
    mp_cols = get_table_columns(engine, "stg", "monthly_performance")

    if not emp_cols:
        raise ValueError("Không tìm thấy bảng stg.employees trong SQL Server.")
    if not mp_cols:
        raise ValueError("Không tìm thấy bảng stg.monthly_performance trong SQL Server.")

    check_required(emp_cols, REQUIRED_EMPLOYEE_COLS, "stg.employees")
    check_required(mp_cols, REQUIRED_MONTHLY_COLS, "stg.monthly_performance")

    time_filter_sql = ""
    if enable_lookback and "Month_Start_Date" in mp_cols:
        time_filter_sql = f"""
        AND TRY_CAST(mp.[Month_Start_Date] AS DATE) < CAST('{prediction_date_str}' AS DATE)
        AND TRY_CAST(mp.[Month_Start_Date] AS DATE) >= DATEADD(MONTH, -{lookback_months_value}, CAST('{prediction_date_str}' AS DATE))
        """

    promotion_expr = optional_avg_expr(mp_cols, "Promotion_Flag", "Promotion_Rate")
    salary_increase_expr = optional_avg_expr(mp_cols, "Salary_Increase_Flag", "Salary_Increase_Rate")
    bonus_expr = optional_avg_expr(mp_cols, "Monthly_Bonus", "Avg_Monthly_Bonus")
    benefits_expr = optional_avg_expr(mp_cols, "Benefits_Cost", "Avg_Benefits_Cost")

    query = f"""
    SELECT
        e.[Employee_Id],
        TRY_CAST(e.[Age] AS FLOAT) AS [Age],
        TRY_CAST(e.[Base_Salary_Annual] AS FLOAT) AS [Base_Salary_Annual],
        DATEDIFF(MONTH, TRY_CAST(e.[Hire_Date] AS DATE), CAST('{prediction_date_str}' AS DATE)) AS [Tenure_Months_As_Of],
        TRY_CAST(e.[Is_Exit_Flag] AS INT) AS [Is_Exit_Flag],

        AVG(TRY_CAST(mp.[Performance_Rating] AS FLOAT)) AS [Avg_Performance_Rating],
        AVG(TRY_CAST(mp.[Training_Hours] AS FLOAT)) AS [Avg_Training_Hours],
        AVG(TRY_CAST(mp.[Overtime_Hours] AS FLOAT)) AS [Avg_Overtime_Hours],
        AVG(TRY_CAST(mp.[Absenteeism_Days] AS FLOAT)) AS [Avg_Absenteeism_Days],
        AVG(TRY_CAST(mp.[Employee_Satisfaction] AS FLOAT)) AS [Avg_Employee_Satisfaction],
        AVG(TRY_CAST(mp.[Engagement_Index] AS FLOAT)) AS [Avg_Engagement_Index],
        AVG(TRY_CAST(mp.[Manager_Evaluation] AS FLOAT)) AS [Avg_Manager_Evaluation],
        {promotion_expr},
        {salary_increase_expr},
        {bonus_expr},
        {benefits_expr}

    FROM stg.employees e
    LEFT JOIN stg.monthly_performance mp
        ON e.[Employee_Id] = mp.[Employee_Id]
        {time_filter_sql}
    WHERE e.[Is_Exit_Flag] IS NOT NULL
    GROUP BY
        e.[Employee_Id], e.[Age], e.[Base_Salary_Annual], e.[Hire_Date], e.[Is_Exit_Flag]
    """

    df = pd.read_sql(query, con=engine)

    # Nếu người dùng chọn ngày dự đoán nằm ngoài khoảng dữ liệu KPI,
    # lookback có thể làm toàn bộ KPI bị NULL. Khi đó Feature Importance
    # chỉ còn vài cột như Age, Salary, Tenure. App tự fallback về toàn bộ KPI
    # để mô hình có đủ biến phân tích hơn.
    if bool(time_filter_sql.strip()) and "Avg_Performance_Rating" in df.columns:
        if df["Avg_Performance_Rating"].isna().all():
            query_no_filter = query.replace(time_filter_sql, "")
            df = pd.read_sql(query_no_filter, con=engine)
            query = query_no_filter
            time_filter_sql = ""

    for col in BASE_FEATURE_COLS + ["Is_Exit_Flag"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Tenure_Months_As_Of"] = df["Tenure_Months_As_Of"].clip(lower=0)
    df = df[df["Is_Exit_Flag"].isin([0, 1])].copy()
    df["Is_Exit_Flag"] = df["Is_Exit_Flag"].astype(int)

    employee_total = int(pd.read_sql("SELECT COUNT(*) AS n FROM stg.employees", con=engine)["n"].iloc[0])
    monthly_total = int(pd.read_sql("SELECT COUNT(*) AS n FROM stg.monthly_performance", con=engine)["n"].iloc[0])

    min_kpi_date = max_kpi_date = None
    if "Month_Start_Date" in mp_cols:
        q_date = """
        SELECT MIN(TRY_CAST([Month_Start_Date] AS DATE)) AS Min_Date,
               MAX(TRY_CAST([Month_Start_Date] AS DATE)) AS Max_Date
        FROM stg.monthly_performance
        """
        d = pd.read_sql(q_date, con=engine)
        min_kpi_date, max_kpi_date = d["Min_Date"].iloc[0], d["Max_Date"].iloc[0]

    dq = {
        "employee_total": employee_total,
        "monthly_total": monthly_total,
        "model_rows": len(df),
        "employee_with_kpi": int(df["Avg_Performance_Rating"].notna().sum()),
        "employee_without_kpi": int(df["Avg_Performance_Rating"].isna().sum()),
        "min_kpi_date": min_kpi_date,
        "max_kpi_date": max_kpi_date,
        "time_filter_used": bool(time_filter_sql.strip()),
        "emp_cols": emp_cols,
        "mp_cols": mp_cols,
        "sql_query": query,
    }
    return df, dq

# ============================================================
# FEATURE ENGINEERING
# ============================================================

def add_feature_engineering(df: pd.DataFrame):
    data = df.copy()
    for col in BASE_FEATURE_COLS:
        if col not in data.columns:
            data[col] = np.nan
        data[col] = pd.to_numeric(data[col], errors="coerce")

    tenure_safe = data["Tenure_Months_As_Of"].replace(0, np.nan)
    training_safe = data["Avg_Training_Hours"].replace(0, np.nan)

    data["Salary_Per_Tenure"] = data["Base_Salary_Annual"] / tenure_safe
    data["Overtime_Training_Ratio"] = data["Avg_Overtime_Hours"] / training_safe
    data["Absence_Per_Tenure"] = data["Avg_Absenteeism_Days"] / tenure_safe
    data["Satisfaction_Engagement_Mean"] = (data["Avg_Employee_Satisfaction"] + data["Avg_Engagement_Index"]) / 2
    data["Performance_Manager_Gap"] = data["Avg_Performance_Rating"] - data["Avg_Manager_Evaluation"]
    data["Workload_Risk_Index"] = data["Avg_Overtime_Hours"] + data["Avg_Absenteeism_Days"]
    data["Development_Index"] = data["Avg_Training_Hours"] + data["Avg_Performance_Rating"]
    return data.replace([np.inf, -np.inf], np.nan)


def get_shap_description():
    return pd.DataFrame(
        {
            "Nội dung": [
                "Mục đích",
                "Cách hiểu SHAP Value > 0",
                "Cách hiểu SHAP Value < 0",
                "Mức độ ảnh hưởng",
                "Vị trí sử dụng trong hệ thống",
                "Lưu ý nghiệp vụ",
            ],
            "Đặc tả": [
                "SHAP dùng để giải thích vì sao mô hình dự đoán một nhân viên có nguy cơ nghỉ việc cao hoặc thấp.",
                "Biến đó đang đẩy dự đoán về phía lớp nghỉ việc, tức làm tăng xác suất nghỉ việc.",
                "Biến đó đang đẩy dự đoán về phía lớp ở lại, tức làm giảm xác suất nghỉ việc.",
                "Giá trị tuyệt đối của SHAP càng lớn thì biến đó càng ảnh hưởng mạnh đến dự đoán cá nhân.",
                "SHAP được đặt ở phần dự đoán từng nhân viên mới và phần giải thích từng nhân viên trong DWH/STG.",
                "SHAP là công cụ hỗ trợ giải thích mô hình, không phải kết luận tuyệt đối về việc nhân viên chắc chắn nghỉ hay ở lại.",
            ],
        }
    )


def get_feature_engineering_pipeline_description():
    return pd.DataFrame(
        {
            "Bước": [
                "1. Chọn dữ liệu đầu vào",
                "2. Chống leakage",
                "3. Tổng hợp KPI",
                "4. Tạo biến thâm niên",
                "5. Tạo biến dẫn xuất",
                "6. Xử lý thiếu",
                "7. Huấn luyện mô hình",
            ],
            "Đặc tả xử lý": [
                "Dữ liệu lấy từ stg.employees và stg.monthly_performance trong SQL Server.",
                "Không đưa Exit_Date vào feature; Is_Exit_Flag chỉ dùng làm nhãn mục tiêu y.",
                "Các KPI theo tháng được lấy trung bình theo Employee_Id; nếu lookback không có dữ liệu, app fallback để tránh mất toàn bộ KPI.",
                "Tenure_Months_As_Of được tính từ Hire_Date đến ngày dự đoán, không tính theo ngày nghỉ việc.",
                "Tạo các biến như Salary_Per_Tenure, Overtime_Training_Ratio, Workload_Risk_Index để mô hình học được quan hệ nghiệp vụ.",
                "Các giá trị thiếu được điền bằng median của tập huấn luyện để mô hình không lỗi khi dự đoán.",
                "Mô hình được đánh giá bằng Accuracy, Balanced Accuracy, Precision, Recall, F1-score, ROC-AUC, PR-AUC, Error Analysis và Threshold Tuning.",
            ],
        }
    )


def get_feature_status_table(df: pd.DataFrame):
    data = add_feature_engineering(df)
    rows = []
    for col in ALL_FEATURE_COLS:
        if col in data.columns:
            non_null = int(data[col].notna().sum())
            total = int(len(data))
            rows.append(
                {
                    "Feature": col,
                    "Số dòng có dữ liệu": non_null,
                    "Tỷ lệ có dữ liệu (%)": round(non_null / total * 100, 2) if total > 0 else 0,
                    "Trạng thái": "Được dùng" if non_null > 0 else "Bị loại vì toàn NULL",
                }
            )
        else:
            rows.append(
                {
                    "Feature": col,
                    "Số dòng có dữ liệu": 0,
                    "Tỷ lệ có dữ liệu (%)": 0,
                    "Trạng thái": "Không có trong dữ liệu",
                }
            )
    return pd.DataFrame(rows)


def prepare_xy(df: pd.DataFrame):
    data = add_feature_engineering(df)
    feature_cols = [c for c in ALL_FEATURE_COLS if c in data.columns]
    X = data[feature_cols].copy().apply(pd.to_numeric, errors="coerce")

    all_null_cols = [c for c in X.columns if X[c].isna().all()]
    if all_null_cols:
        X = X.drop(columns=all_null_cols)
        feature_cols = [c for c in feature_cols if c not in all_null_cols]

    if not feature_cols:
        raise ValueError("Không còn feature nào để huấn luyện sau khi xử lý dữ liệu.")

    medians = X.median(numeric_only=True).fillna(0)
    X = X.fillna(medians)
    y = data["Is_Exit_Flag"].astype(int)
    return X, y, feature_cols, medians


def build_model_input(df: pd.DataFrame, feature_cols: list, medians: pd.Series):
    data = add_feature_engineering(df)
    for col in feature_cols:
        if col not in data.columns:
            data[col] = np.nan
    X = data[feature_cols].copy().apply(pd.to_numeric, errors="coerce")
    return X.fillna(medians)


def get_feature_engineering_description():
    return pd.DataFrame({
        "Biến mới": ENGINEERED_FEATURE_COLS,
        "Công thức": [
            "Base_Salary_Annual / Tenure_Months_As_Of",
            "Avg_Overtime_Hours / Avg_Training_Hours",
            "Avg_Absenteeism_Days / Tenure_Months_As_Of",
            "(Avg_Employee_Satisfaction + Avg_Engagement_Index) / 2",
            "Avg_Performance_Rating - Avg_Manager_Evaluation",
            "Avg_Overtime_Hours + Avg_Absenteeism_Days",
            "Avg_Training_Hours + Avg_Performance_Rating",
        ],
        "Ý nghĩa": [
            "Mức lương theo thâm niên tại thời điểm dự đoán.",
            "Mức làm thêm so với đào tạo, phản ánh áp lực công việc.",
            "Mức vắng mặt theo thâm niên.",
            "Mức hài lòng và gắn kết trung bình.",
            "Chênh lệch giữa hiệu suất và đánh giá quản lý.",
            "Chỉ số áp lực công việc từ làm thêm và vắng mặt.",
            "Chỉ số phát triển nhân viên từ đào tạo và hiệu suất.",
        ],
    })

# ============================================================
# MODELS
# ============================================================

def get_model(name: str):
    if name == "Logistic Regression":
        return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    if name == "Decision Tree":
        return DecisionTreeClassifier(random_state=42, class_weight="balanced", max_depth=8, min_samples_split=10, min_samples_leaf=5)
    if name == "Random Forest":
        return RandomForestClassifier(n_estimators=250, random_state=42, class_weight="balanced", max_depth=10, min_samples_split=10, min_samples_leaf=5, n_jobs=-1)
    if name == "Extra Trees":
        return ExtraTreesClassifier(n_estimators=250, random_state=42, class_weight="balanced", max_depth=10, min_samples_split=10, min_samples_leaf=5, n_jobs=-1)
    if name == "Gradient Boosting":
        return GradientBoostingClassifier(random_state=42, max_depth=3, min_samples_split=10, min_samples_leaf=5)
    return RandomForestClassifier(n_estimators=250, random_state=42, class_weight="balanced", max_depth=10, min_samples_split=10, min_samples_leaf=5, n_jobs=-1)


def get_param_dist(name: str):
    if name == "Logistic Regression":
        return {"C": [0.01, 0.1, 1, 10, 100], "solver": ["lbfgs", "liblinear"]}
    if name == "Decision Tree":
        return {"max_depth": [3, 5, 8, 10, 12], "min_samples_split": [5, 10, 20], "min_samples_leaf": [3, 5, 10], "criterion": ["gini", "entropy"]}
    if name in ["Random Forest", "Extra Trees"]:
        return {"n_estimators": [150, 250, 350], "max_depth": [5, 8, 10, 12], "min_samples_split": [5, 10, 20], "min_samples_leaf": [3, 5, 10], "class_weight": ["balanced", "balanced_subsample"]}
    if name == "Gradient Boosting":
        return {"n_estimators": [100, 200], "learning_rate": [0.01, 0.05, 0.1], "max_depth": [2, 3, 4], "min_samples_split": [5, 10, 20], "min_samples_leaf": [3, 5, 10]}
    return {}


def get_safe_cv_splits(y, max_splits=5):
    counts = pd.Series(y).value_counts()
    if len(counts) < 2:
        return 2
    return min(max_splits, int(counts.min())) if int(counts.min()) >= 2 else 2


def train_model(X_train, y_train, selected_model: str, tuning: bool):
    base_model = get_model(selected_model)
    if not tuning:
        base_model.fit(X_train, y_train)
        return base_model, None, None

    cv_strategy = StratifiedKFold(n_splits=get_safe_cv_splits(y_train, 3), shuffle=True, random_state=42)
    scoring = {"F1": "f1", "Recall": "recall", "Precision": "precision", "ROC_AUC": "roc_auc", "PR_AUC": "average_precision"}
    search = RandomizedSearchCV(base_model, get_param_dist(selected_model), n_iter=15, scoring=scoring, refit="F1", cv=cv_strategy, random_state=42, n_jobs=-1)
    search.fit(X_train, y_train)
    return search.best_estimator_, search.best_params_, pd.DataFrame(search.cv_results_)


def safe_roc_auc(y_true, y_prob):
    try:
        return roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) >= 2 else 0.0
    except Exception:
        return 0.0


def safe_pr_auc(y_true, y_prob):
    try:
        return average_precision_score(y_true, y_prob) if len(np.unique(y_true)) >= 2 else 0.0
    except Exception:
        return 0.0


def evaluate_model(model, X_test, y_test, threshold_value: float):
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= threshold_value).astype(int)
    metrics = {
        "Accuracy": accuracy_score(y_test, y_pred),
        "Balanced Accuracy": balanced_accuracy_score(y_test, y_pred),
        "Precision": precision_score(y_test, y_pred, zero_division=0),
        "Recall": recall_score(y_test, y_pred, zero_division=0),
        "F1-score": f1_score(y_test, y_pred, zero_division=0),
        "ROC-AUC": safe_roc_auc(y_test, y_prob),
        "PR-AUC": safe_pr_auc(y_test, y_prob),
    }
    return metrics, confusion_matrix(y_test, y_pred), classification_report(y_test, y_pred, zero_division=0), y_prob, y_pred


def compare_models(X_train, X_test, y_train, y_test, threshold_value: float):
    rows, trained = [], {}
    for name in ["Logistic Regression", "Decision Tree", "Random Forest", "Extra Trees", "Gradient Boosting"]:
        model = get_model(name)
        model.fit(X_train, y_train)
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= threshold_value).astype(int)
        rows.append({
            "Model": name,
            "Accuracy": accuracy_score(y_test, y_pred),
            "Balanced Accuracy": balanced_accuracy_score(y_test, y_pred),
            "Precision": precision_score(y_test, y_pred, zero_division=0),
            "Recall": recall_score(y_test, y_pred, zero_division=0),
            "F1-score": f1_score(y_test, y_pred, zero_division=0),
            "ROC-AUC": safe_roc_auc(y_test, y_prob),
            "PR-AUC": safe_pr_auc(y_test, y_prob),
        })
        trained[name] = model
    result = pd.DataFrame(rows).sort_values(by=["F1-score", "Recall", "PR-AUC"], ascending=False)
    best_name = result.iloc[0]["Model"]
    return result, best_name, trained[best_name]


def run_cross_validation(model, X, y):
    cv = StratifiedKFold(n_splits=get_safe_cv_splits(y, 5), shuffle=True, random_state=42)
    scoring = {"Accuracy": "accuracy", "Balanced_Accuracy": "balanced_accuracy", "Precision": "precision", "Recall": "recall", "F1": "f1", "ROC_AUC": "roc_auc", "PR_AUC": "average_precision"}
    cv_scores = cross_validate(model, X, y, cv=cv, scoring=scoring, n_jobs=-1, return_train_score=False)
    return pd.DataFrame({
        "Chỉ số": ["Accuracy", "Balanced Accuracy", "Precision", "Recall", "F1-score", "ROC-AUC", "PR-AUC"],
        "Giá trị trung bình": [cv_scores["test_Accuracy"].mean(), cv_scores["test_Balanced_Accuracy"].mean(), cv_scores["test_Precision"].mean(), cv_scores["test_Recall"].mean(), cv_scores["test_F1"].mean(), cv_scores["test_ROC_AUC"].mean(), cv_scores["test_PR_AUC"].mean()],
        "Độ lệch chuẩn": [cv_scores["test_Accuracy"].std(), cv_scores["test_Balanced_Accuracy"].std(), cv_scores["test_Precision"].std(), cv_scores["test_Recall"].std(), cv_scores["test_F1"].std(), cv_scores["test_ROC_AUC"].std(), cv_scores["test_PR_AUC"].std()],
    })


def find_best_threshold(y_true, y_prob):
    rows = []
    for th in np.arange(0.1, 0.91, 0.05):
        y_pred = (y_prob >= th).astype(int)
        rows.append({
            "Threshold": round(float(th), 2),
            "Precision": precision_score(y_true, y_pred, zero_division=0),
            "Recall": recall_score(y_true, y_pred, zero_division=0),
            "F1-score": f1_score(y_true, y_pred, zero_division=0),
        })
    threshold_df = pd.DataFrame(rows)
    best = threshold_df.sort_values(by=["F1-score", "Recall"], ascending=False).iloc[0]
    return threshold_df, float(best["Threshold"])


def build_error_analysis(y_true, y_pred, y_prob):
    error_df = pd.DataFrame({"Actual": y_true.values, "Predicted": y_pred, "Exit_Probability": y_prob}, index=y_true.index)
    labels = ["TN - Dự đoán đúng ở lại", "FP - Cảnh báo nhầm nghỉ việc", "FN - Bỏ sót nhân viên nghỉ việc", "TP - Dự đoán đúng nghỉ việc"]
    conditions = [
        (error_df["Actual"] == 0) & (error_df["Predicted"] == 0),
        (error_df["Actual"] == 0) & (error_df["Predicted"] == 1),
        (error_df["Actual"] == 1) & (error_df["Predicted"] == 0),
        (error_df["Actual"] == 1) & (error_df["Predicted"] == 1),
    ]
    error_df["Loại kết quả"] = np.select(conditions, labels, default="Không xác định")
    error_summary = error_df["Loại kết quả"].value_counts().reindex(labels, fill_value=0).reset_index()
    error_summary.columns = ["Loại kết quả", "Số lượng"]
    total = error_summary["Số lượng"].sum()
    error_summary["Tỷ lệ (%)"] = (error_summary["Số lượng"] / total * 100).round(2) if total > 0 else 0.0
    return error_df, error_summary

# ============================================================
# SHAP
# ============================================================

def get_shap_values_for_class_1(model, X_background: pd.DataFrame, X_one: pd.DataFrame):
    if not SHAP_AVAILABLE:
        return None, "Chưa cài thư viện shap. Hãy chạy: python -m pip install shap"
    try:
        tree_model_names = ["DecisionTreeClassifier", "RandomForestClassifier", "ExtraTreesClassifier", "GradientBoostingClassifier"]
        if type(model).__name__ in tree_model_names:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_one)
            if isinstance(shap_values, list):
                return shap_values[1][0], None
            arr = np.array(shap_values)
            if arr.ndim == 3:
                return arr[0, :, 1], None
            if arr.ndim == 2:
                return arr[0], None
        bg = X_background.sample(n=min(150, len(X_background)), random_state=42)
        explainer = shap.Explainer(model.predict_proba, bg)
        exp = explainer(X_one)
        vals = exp.values
        if vals.ndim == 3:
            return vals[0, :, 1], None
        if vals.ndim == 2:
            return vals[0], None
        return np.array(vals).ravel(), None
    except Exception as e:
        return None, str(e)


def make_local_explanation_df(model, X_background: pd.DataFrame, X_one: pd.DataFrame):
    """
    Tạo bảng giải thích SHAP cho 1 dự đoán.
    Hàm này LUÔN trả về đúng 2 giá trị:
    - explanation_df
    - error

    Sửa lỗi: ValueError: too many values to unpack (expected 2)
    """

    shap_values, error = get_shap_values_for_class_1(
        model=model,
        X_background=X_background,
        X_one=X_one,
    )

    if error is not None:
        return None, error

    shap_values = np.array(shap_values).reshape(-1)

    if len(shap_values) != X_one.shape[1]:
        return None, (
            f"Số lượng SHAP values ({len(shap_values)}) không khớp "
            f"với số lượng feature ({X_one.shape[1]})."
        )

    explanation_df = pd.DataFrame(
        {
            "Biến đầu vào": X_one.columns.tolist(),
            "Giá trị": X_one.iloc[0].values,
            "SHAP Value": shap_values,
        }
    )

    explanation_df["Mức độ ảnh hưởng"] = explanation_df["SHAP Value"].abs()

    explanation_df["Tác động"] = np.where(
        explanation_df["SHAP Value"] > 0,
        "Làm tăng nguy cơ nghỉ việc",
        "Làm giảm nguy cơ nghỉ việc",
    )

    explanation_df = explanation_df.sort_values(
        "Mức độ ảnh hưởng",
        ascending=False,
    )

    return explanation_df, None

# ============================================================
# PLOTS
# ============================================================

def plot_label_imbalance(target_count: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    bars = ax.bar(target_count["Nhãn"], target_count["Số lượng"], color=["#2E86DE", "#E74C3C"], edgecolor="#2C3E50", linewidth=0.8)
    ax.set_title("Phân bố nhãn trong bài toán dự đoán nghỉ việc", fontsize=13, fontweight="bold", pad=14, color="#1F4E79")
    ax.set_xlabel("Nhãn nhân viên", fontsize=12); ax.set_ylabel("Số lượng nhân viên", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.35); ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    for bar, count, ratio in zip(bars, target_count["Số lượng"], target_count["Tỷ lệ (%)"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{int(count):,}\n({ratio:.2f}%)", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout(); return fig


def plot_confusion_matrix(cm):
    fig, ax = plt.subplots(figsize=(4.8, 3.8)); im = ax.imshow(cm, cmap="Blues")
    ax.set_title("Confusion Matrix", fontsize=13, fontweight="bold", pad=15, color="#1F4E79")
    ax.set_xlabel("Predicted Label", fontsize=12); ax.set_ylabel("Actual Label", fontsize=12)
    ax.set_xticks([0, 1]); ax.set_yticks([0, 1]); ax.set_xticklabels(["Stay", "Exit"]); ax.set_yticklabels(["Stay", "Exit"])
    max_value = cm.max() if cm.size else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            value = cm[i, j]
            ax.text(j, i, str(value), ha="center", va="center", fontsize=13, fontweight="bold", color="white" if max_value > 0 and value > max_value/2 else "#1F1F1F")
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); fig.tight_layout(); return fig


def plot_threshold_tuning(threshold_df: pd.DataFrame, suggested_threshold: float):
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.plot(threshold_df["Threshold"], threshold_df["Precision"], marker="o", linewidth=2, label="Precision", color="#2E86DE")
    ax.plot(threshold_df["Threshold"], threshold_df["Recall"], marker="o", linewidth=2, label="Recall", color="#E74C3C")
    ax.plot(threshold_df["Threshold"], threshold_df["F1-score"], marker="o", linewidth=2, label="F1-score", color="#27AE60")
    ax.axvline(suggested_threshold, linestyle="--", linewidth=2, color="#2C3E50", label=f"Ngưỡng gợi ý = {suggested_threshold:.2f}")
    ax.set_title("Threshold Tuning - Precision, Recall và F1-score", fontsize=14, fontweight="bold", pad=14, color="#1F4E79")
    ax.set_xlabel("Ngưỡng dự đoán nghỉ việc"); ax.set_ylabel("Giá trị chỉ số"); ax.set_ylim(0, 1.05)
    ax.grid(axis="both", linestyle="--", alpha=0.35); ax.legend(frameon=True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    fig.tight_layout(); return fig


def plot_error_analysis(error_summary: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(7.6, 3.8)); colors = ["#2E86DE", "#F39C12", "#E74C3C", "#27AE60"]
    bars = ax.bar(error_summary["Loại kết quả"], error_summary["Số lượng"], color=colors, edgecolor="#2C3E50", linewidth=0.8)
    ax.set_title("Error Analysis - Phân tích đúng/sai của mô hình", fontsize=14, fontweight="bold", pad=14, color="#1F4E79")
    ax.set_xlabel("Loại kết quả dự đoán"); ax.set_ylabel("Số lượng nhân viên")
    ax.grid(axis="y", linestyle="--", alpha=0.35); ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False); plt.xticks(rotation=20, ha="right")
    for bar, count, ratio in zip(bars, error_summary["Số lượng"], error_summary["Tỷ lệ (%)"]):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), f"{int(count):,}\n({ratio:.2f}%)", ha="center", va="bottom", fontsize=10, fontweight="bold")
    fig.tight_layout(); return fig


def plot_error_probability_distribution(error_df: pd.DataFrame):
    groups = ["TN - Dự đoán đúng ở lại", "FP - Cảnh báo nhầm nghỉ việc", "FN - Bỏ sót nhân viên nghỉ việc", "TP - Dự đoán đúng nghỉ việc"]
    data_to_plot, names = [], []
    for g in groups:
        vals = error_df.loc[error_df["Loại kết quả"] == g, "Exit_Probability"].values
        if len(vals) > 0:
            data_to_plot.append(vals); names.append(g)
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    if not data_to_plot:
        ax.text(0.5, 0.5, "Không có dữ liệu để vẽ biểu đồ.", ha="center", va="center"); ax.axis("off"); return fig
    bp = ax.boxplot(data_to_plot, labels=names, showmeans=True, patch_artist=True)
    for patch, color in zip(bp["boxes"], ["#2E86DE", "#F39C12", "#E74C3C", "#27AE60"]):
        patch.set_facecolor(color); patch.set_alpha(0.55)
    ax.set_title("Phân bố xác suất nghỉ việc theo từng loại lỗi", fontsize=14, fontweight="bold", pad=14, color="#1F4E79")
    ax.set_xlabel("Loại kết quả dự đoán"); ax.set_ylabel("Xác suất nghỉ việc"); ax.set_ylim(0, 1.05)
    ax.grid(axis="y", linestyle="--", alpha=0.35); plt.xticks(rotation=20, ha="right")
    fig.tight_layout(); return fig


def plot_feature_importance(model, feature_cols, top_n=15):
    if hasattr(model, "feature_importances_"):
        values = model.feature_importances_
    elif hasattr(model, "coef_"):
        values = np.abs(model.coef_[0])
    else:
        return None, None
    importance_df = pd.DataFrame({"Feature": feature_cols, "Importance": values}).sort_values("Importance", ascending=False)
    top_df = importance_df.head(top_n).sort_values("Importance", ascending=True)
    fig, ax = plt.subplots(figsize=(7.8, 5.2))
    bars = ax.barh(top_df["Feature"], top_df["Importance"], color="#2E86DE", edgecolor="#1B4F72", linewidth=0.8)
    ax.set_title(f"Top {top_n} Feature Importance", fontsize=14, fontweight="bold", pad=16, color="#1F4E79")
    ax.set_xlabel("Importance Score"); ax.set_ylabel("Feature"); ax.grid(axis="x", linestyle="--", alpha=0.35); ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    max_value = top_df["Importance"].max(); offset = max_value * 0.015 if max_value > 0 else 0.001
    for bar in bars:
        width = bar.get_width(); ax.text(width + offset, bar.get_y() + bar.get_height()/2, f"{width:.3f}", va="center", fontsize=10)
    ax.set_xlim(0, max_value * 1.18 if max_value > 0 else 1); fig.tight_layout(); return fig, importance_df


def plot_local_shap_bar(explanation_df: pd.DataFrame, top_n: int = 10):
    plot_df = explanation_df.head(top_n).sort_values("SHAP Value", ascending=True)
    colors = ["#E74C3C" if v > 0 else "#3498DB" for v in plot_df["SHAP Value"]]
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    bars = ax.barh(plot_df["Biến đầu vào"], plot_df["SHAP Value"], color=colors, edgecolor="#2C3E50", linewidth=0.8)
    ax.axvline(0, color="#2C3E50", linewidth=1.3)
    ax.set_title("SHAP Explanation - Các yếu tố ảnh hưởng đến dự đoán", fontsize=13, fontweight="bold", pad=16, color="#1F4E79")
    ax.set_xlabel("SHAP Value"); ax.set_ylabel("Feature"); ax.grid(axis="x", linestyle="--", alpha=0.35); ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    max_abs = max(abs(plot_df["SHAP Value"].min()), abs(plot_df["SHAP Value"].max())) if not plot_df.empty else 1
    offset = max_abs * 0.03 if max_abs > 0 else 0.001
    for bar in bars:
        width = bar.get_width(); y = bar.get_y() + bar.get_height()/2
        if width >= 0:
            ax.text(width + offset, y, f"{width:.3f}", va="center", ha="left", fontsize=10)
        else:
            ax.text(width - offset, y, f"{width:.3f}", va="center", ha="right", fontsize=10)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#E74C3C", label="Làm tăng nguy cơ nghỉ việc"), Patch(facecolor="#3498DB", label="Làm giảm nguy cơ nghỉ việc")], loc="lower right", frameon=True)
    ax.set_xlim(-max_abs * 1.25, max_abs * 1.25); fig.tight_layout(); return fig


def plot_risk_distribution(prediction_df: pd.DataFrame):
    order = ["Thấp", "Trung bình", "Cao"]
    count_df = prediction_df["Risk_Level"].value_counts().reindex(order, fill_value=0).reset_index()
    count_df.columns = ["Risk_Level", "Số lượng"]
    total = count_df["Số lượng"].sum(); count_df["Tỷ lệ (%)"] = (count_df["Số lượng"] / total * 100).round(2) if total else 0
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    bars = ax.bar(count_df["Risk_Level"], count_df["Số lượng"], color=["#27AE60", "#F39C12", "#E74C3C"], edgecolor="#2C3E50", linewidth=0.8)
    ax.set_title("Phân bố mức rủi ro nghỉ việc trong dữ liệu DWH", fontsize=13, fontweight="bold", pad=14, color="#1F4E79")
    ax.set_xlabel("Mức rủi ro"); ax.set_ylabel("Số lượng nhân viên"); ax.grid(axis="y", linestyle="--", alpha=0.35); ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    for bar, count, ratio in zip(bars, count_df["Số lượng"], count_df["Tỷ lệ (%)"]):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), f"{int(count):,}\n({ratio:.2f}%)", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout(); return fig, count_df

# ============================================================
# INPUT/PREDICT HELPERS
# ============================================================

def get_reference_values(df: pd.DataFrame):
    X, y, _, _ = prepare_xy(df)
    ref = X.copy(); ref["Is_Exit_Flag"] = y.values
    stay = ref[ref["Is_Exit_Flag"] == 0]
    if stay.empty: stay = ref
    return {col: float(stay[col].median()) if col in stay.columns else 0.0 for col in BASE_FEATURE_COLS}


def create_new_employee_input_form(ref_values: dict):
    st.markdown("### Nhập thông tin nhân viên mới")
    st.caption("Giá trị mặc định lấy theo trung vị của nhóm nhân viên ở lại để hạn chế nhập sai thang đo.")
    c1, c2, c3 = st.columns(3)
    with c1:
        age = st.number_input("Tuổi nhân viên", 18.0, 70.0, float(round(ref_values.get("Age", 35), 1)), 1.0)
        base_salary = st.number_input("Lương năm cơ bản", 0.0, value=float(round(ref_values.get("Base_Salary_Annual", 35000), 2)), step=1000.0)
        tenure = st.number_input("Thâm niên đến ngày dự đoán - tháng", 0.0, value=float(round(ref_values.get("Tenure_Months_As_Of", 36), 1)), step=1.0)
        promotion = st.number_input("Tỷ lệ tháng có thăng chức", 0.0, 1.0, float(round(ref_values.get("Promotion_Rate", 0), 3)), 0.05)
    with c2:
        perf = st.number_input("Điểm hiệu suất trung bình (0-5)", 0.0, 5.0, float(round(ref_values.get("Avg_Performance_Rating", 3.5), 2)), 0.1)
        training = st.number_input("Số giờ đào tạo trung bình", 0.0, value=float(round(ref_values.get("Avg_Training_Hours", 8), 2)), step=0.5)
        overtime = st.number_input("Số giờ làm thêm trung bình", 0.0, value=float(round(ref_values.get("Avg_Overtime_Hours", 5), 2)), step=0.5)
        salary_inc = st.number_input("Tỷ lệ tháng được tăng lương", 0.0, 1.0, float(round(ref_values.get("Salary_Increase_Rate", 0), 3)), 0.05)
    with c3:
        absence = st.number_input("Số ngày vắng mặt trung bình", 0.0, value=float(round(ref_values.get("Avg_Absenteeism_Days", 1), 2)), step=0.5)
        satisfaction = st.number_input("Mức hài lòng trung bình (0-10)", 0.0, 10.0, float(round(ref_values.get("Avg_Employee_Satisfaction", 8), 2)), 0.1)
        engagement = st.number_input("Chỉ số gắn kết trung bình (0-10)", 0.0, 10.0, float(round(ref_values.get("Avg_Engagement_Index", 8), 2)), 0.1)
        manager = st.number_input("Đánh giá quản lý trung bình (0-5)", 0.0, 5.0, float(round(ref_values.get("Avg_Manager_Evaluation", 3.5), 2)), 0.1)
    c4, c5 = st.columns(2)
    with c4:
        bonus = st.number_input("Thưởng tháng trung bình", 0.0, value=float(round(ref_values.get("Avg_Monthly_Bonus", 0), 2)), step=100.0)
    with c5:
        benefits = st.number_input("Chi phí phúc lợi trung bình", 0.0, value=float(round(ref_values.get("Avg_Benefits_Cost", 0), 2)), step=100.0)
    return pd.DataFrame([{ 
        "Age": age, "Base_Salary_Annual": base_salary, "Tenure_Months_As_Of": tenure,
        "Avg_Performance_Rating": perf, "Avg_Training_Hours": training, "Avg_Overtime_Hours": overtime,
        "Avg_Absenteeism_Days": absence, "Avg_Employee_Satisfaction": satisfaction, "Avg_Engagement_Index": engagement,
        "Avg_Manager_Evaluation": manager, "Promotion_Rate": promotion, "Salary_Increase_Rate": salary_inc,
        "Avg_Monthly_Bonus": bonus, "Avg_Benefits_Cost": benefits,
    }])


def predict_with_model(model, input_df, feature_cols, medians, threshold_value):
    X_input = build_model_input(input_df, feature_cols, medians)
    probs = model.predict_proba(X_input)[:, 1]
    preds = (probs >= threshold_value).astype(int)
    result = input_df.copy(); result["Exit_Probability"] = probs; result["Predicted_Is_Exit"] = preds
    result["Predicted_Label"] = np.where(preds == 1, "Nghi viec", "O lai")
    result["Risk_Level"] = pd.cut(result["Exit_Probability"], bins=[-0.01, 0.3, 0.6, 1.0], labels=["Thấp", "Trung bình", "Cao"])
    return result, X_input


def create_template_csv(ref_values: dict):
    row = {
        "Employee_Id": "NEW001",
        "Age": round(ref_values.get("Age", 35), 2),
        "Base_Salary_Annual": round(ref_values.get("Base_Salary_Annual", 35000), 2),
        "Tenure_Months_As_Of": round(ref_values.get("Tenure_Months_As_Of", 36), 2),
        "Avg_Performance_Rating": round(ref_values.get("Avg_Performance_Rating", 3.5), 2),
        "Avg_Training_Hours": round(ref_values.get("Avg_Training_Hours", 8), 2),
        "Avg_Overtime_Hours": round(ref_values.get("Avg_Overtime_Hours", 5), 2),
        "Avg_Absenteeism_Days": round(ref_values.get("Avg_Absenteeism_Days", 1), 2),
        "Avg_Employee_Satisfaction": round(ref_values.get("Avg_Employee_Satisfaction", 8), 2),
        "Avg_Engagement_Index": round(ref_values.get("Avg_Engagement_Index", 8), 2),
        "Avg_Manager_Evaluation": round(ref_values.get("Avg_Manager_Evaluation", 3.5), 2),
        "Promotion_Rate": round(ref_values.get("Promotion_Rate", 0), 3),
        "Salary_Increase_Rate": round(ref_values.get("Salary_Increase_Rate", 0), 3),
        "Avg_Monthly_Bonus": round(ref_values.get("Avg_Monthly_Bonus", 0), 2),
        "Avg_Benefits_Cost": round(ref_values.get("Avg_Benefits_Cost", 0), 2),
    }
    return pd.DataFrame([row])

# ============================================================
# SESSION STATE
# ============================================================

default_states = {
    "df": None, "data_quality": None, "model": None, "feature_cols": None, "medians": None,
    "metrics": None, "cm": None, "report": None, "threshold_df": None, "suggested_threshold": None,
    "cv_result": None, "cv_summary": None, "compare_df": None, "best_model_name": None,
    "error_df": None, "error_summary": None, "dwh_prediction_result": None, "batch_result": None,
}
for key, value in default_states.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ============================================================
# TABS
# ============================================================

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. Nạp dữ liệu SQL", "2. Huấn luyện & đánh giá", "3. Dự đoán nhân viên mới", "4. Dự đoán nhân viên trong DWH", "5. Dự đoán hàng loạt CSV",
])

# ============================================================
# TAB 1
# ============================================================

with tab1:
    st.subheader("1. Nạp dữ liệu trực tiếp từ SQL Server")
    if st.button("Nạp dữ liệu từ SQL Server", type="primary"):
        try:
            with st.spinner("Đang kết nối SQL Server và tổng hợp dữ liệu..."):
                df, dq = load_data_from_sql(server, database, driver, str(prediction_date), lookback_months, use_lookback)
            if df.empty:
                st.error("Dữ liệu rỗng. Hãy kiểm tra lại SQL Server."); st.stop()
            st.session_state.df = df; st.session_state.data_quality = dq
            for key in ["model", "feature_cols", "medians", "metrics", "cm", "report", "threshold_df", "suggested_threshold", "cv_result", "cv_summary", "compare_df", "best_model_name", "error_df", "error_summary", "dwh_prediction_result", "batch_result"]:
                st.session_state[key] = None
            st.success("Nạp dữ liệu SQL thành công.")
        except Exception as e:
            st.error("Nạp dữ liệu từ SQL Server thất bại."); st.exception(e)

    if st.session_state.df is not None:
        df, dq = st.session_state.df, st.session_state.data_quality
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nhân viên trong SQL", f"{dq['employee_total']:,}")
        c2.metric("Dòng KPI tháng", f"{dq['monthly_total']:,}")
        c3.metric("Dòng dùng cho ML", f"{dq['model_rows']:,}")
        c4.metric("Nhân viên thiếu KPI", f"{dq['employee_without_kpi']:,}")

        st.markdown("### Thông tin thời gian KPI")
        time_info_df = pd.DataFrame([{
            "Có cột Month_Start_Date": "Có" if "Month_Start_Date" in dq["mp_cols"] else "Không",
            "Có lọc lookback": "Có" if dq["time_filter_used"] else "Không",
            "Ngày KPI nhỏ nhất": dq["min_kpi_date"], "Ngày KPI lớn nhất": dq["max_kpi_date"],
            "Ngày dự đoán": str(prediction_date), "Số tháng lookback": lookback_months,
        }])
        st.dataframe(time_info_df, use_container_width=True)

        st.markdown("### Xem trước dữ liệu sau tổng hợp từ SQL")
        st.dataframe(df.head(30), use_container_width=True)

        st.markdown("### Thống kê thang đo feature")
        X_ref, y_ref, feature_cols_ref, medians_ref = prepare_xy(df)
        profile_df = X_ref.describe().T[["min", "25%", "50%", "75%", "max", "mean"]].reset_index().rename(columns={"index": "Feature"})
        st.dataframe(profile_df, use_container_width=True)
        st.caption("Base_Salary_Annual là lương năm theo đơn vị dữ liệu gốc, không nhập theo VNĐ. Employee_Satisfaction và Engagement_Index thường dùng thang 0-10.")

        st.markdown("### Phân bố biến mục tiêu")
        label_counts = df["Is_Exit_Flag"].value_counts().sort_index()
        stay_count, exit_count = int(label_counts.get(0, 0)), int(label_counts.get(1, 0))
        total_count = stay_count + exit_count
        stay_ratio = stay_count / total_count if total_count else 0
        exit_ratio = exit_count / total_count if total_count else 0
        target_count = pd.DataFrame({"Nhãn": ["Ở lại", "Nghỉ việc"], "Giá trị nhãn": [0, 1], "Số lượng": [stay_count, exit_count], "Tỷ lệ (%)": [round(stay_ratio*100, 2), round(exit_ratio*100, 2)]})
        st.dataframe(target_count, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Nhân viên ở lại", f"{stay_count:,}", f"{stay_ratio:.2%}")
        c2.metric("Nhân viên nghỉ việc", f"{exit_count:,}", f"{exit_ratio:.2%}")
        imbalance_ratio = stay_count / exit_count if exit_count > 0 else np.inf
        c3.metric("Tỷ lệ lệch nhãn", "Không xác định" if np.isinf(imbalance_ratio) else f"{imbalance_ratio:.2f}:1")
        st.pyplot(plot_label_imbalance(target_count), use_container_width=False)
        if imbalance_ratio >= 3:
            st.warning("Dữ liệu có mất cân bằng nhãn. Mô hình cần ưu tiên Recall, F1-score, PR-AUC và Balanced Accuracy.")
        else:
            st.success("Dữ liệu không bị mất cân bằng nhãn nghiêm trọng.")

# ============================================================
# TAB 2
# ============================================================

with tab2:
    st.subheader("2. Huấn luyện và đánh giá mô hình")
    if st.session_state.df is None:
        st.warning("Bạn cần nạp dữ liệu SQL ở Tab 1 trước.")
    else:
        df = st.session_state.df
        st.markdown("### Đặc tả Feature Engineering")
        st.write(
            "Feature Engineering là bước tạo thêm biến đầu vào từ dữ liệu HR sau ETL. "
            "Mục tiêu là giúp mô hình học được các dấu hiệu nghiệp vụ như áp lực công việc, mức gắn kết, thâm niên, đào tạo và đãi ngộ."
        )
        st.dataframe(get_feature_engineering_description(), use_container_width=True)

        st.markdown("### Đặc tả quy trình xử lý feature")
        st.dataframe(get_feature_engineering_pipeline_description(), use_container_width=True)

        with st.expander("Kiểm tra trạng thái các feature được đưa vào mô hình"):
            st.dataframe(get_feature_status_table(df), use_container_width=True)
            st.caption(
                "Nếu Feature Importance chỉ hiển thị 4 cột, nguyên nhân thường là nhiều cột KPI bị NULL toàn bộ do khoảng lookback không có dữ liệu. "
                "Bản code này đã thêm fallback: nếu lookback làm KPI rỗng, app tự nạp lại KPI không lọc thời gian để tránh chỉ còn vài feature."
            )
        st.markdown("### Chiến lược thiết kế mô hình")
        st.write("""
        Hệ thống sử dụng các feature số sau ETL và các biến feature engineering.
        Không dùng `Exit_Date` làm feature. `Is_Exit_Flag` chỉ dùng làm nhãn mục tiêu.
        Dữ liệu được chia train/test bằng stratify để giữ tỷ lệ nhãn nghỉ việc/ở lại.
        """)

        if st.button("So sánh tất cả mô hình", type="secondary"):
            try:
                X, y, feature_cols, medians = prepare_xy(df)
                if y.nunique() < 2: st.error("Biến Is_Exit_Flag chỉ có 1 lớp, không thể huấn luyện."); st.stop()
                X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=42, stratify=y)
                with st.spinner("Đang so sánh các mô hình..."):
                    compare_df, best_name, best_model = compare_models(X_train, X_test, y_train, y_test, threshold)
                st.session_state.compare_df = compare_df; st.session_state.best_model_name = best_name
                st.markdown("### Bảng so sánh mô hình"); st.dataframe(compare_df, use_container_width=True)
                st.success(f"Mô hình được đề xuất: {best_name}")
            except Exception as e:
                st.error("So sánh mô hình thất bại."); st.exception(e)

        if st.session_state.compare_df is not None:
            st.markdown("### Kết quả so sánh mô hình đã chạy")
            st.dataframe(st.session_state.compare_df, use_container_width=True)

        if st.button("Huấn luyện mô hình", type="primary"):
            try:
                X, y, feature_cols, medians = prepare_xy(df)
                if y.nunique() < 2: st.error("Biến Is_Exit_Flag chỉ có 1 lớp, không thể huấn luyện."); st.stop()
                X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=42, stratify=y)
                with st.spinner("Đang huấn luyện mô hình..."):
                    model, best_params, cv_result = train_model(X_train, y_train, model_name, use_tuning)
                metrics, cm, report, y_prob, y_pred = evaluate_model(model, X_test, y_test, threshold)
                threshold_df, suggested_threshold = find_best_threshold(y_test, y_prob)
                error_df, error_summary = build_error_analysis(y_test, y_pred, y_prob)
                cv_summary = run_cross_validation(get_model(model_name), X, y)
                st.session_state.model = model; st.session_state.feature_cols = feature_cols; st.session_state.medians = medians
                st.session_state.metrics = metrics; st.session_state.cm = cm; st.session_state.report = report
                st.session_state.threshold_df = threshold_df; st.session_state.suggested_threshold = suggested_threshold
                st.session_state.error_df = error_df; st.session_state.error_summary = error_summary; st.session_state.cv_summary = cv_summary; st.session_state.cv_result = cv_result
                joblib.dump({"model": model, "features": feature_cols, "medians": medians, "model_name": model_name, "threshold": threshold, "metrics": metrics, "best_params": best_params, "suggested_threshold": suggested_threshold}, "best_attrition_model.pkl")
                st.success("Huấn luyện mô hình thành công. Đã lưu best_attrition_model.pkl")
                if best_params is not None: st.markdown("### Bộ tham số tốt nhất"); st.json(best_params)
            except Exception as e:
                st.error("Huấn luyện mô hình thất bại."); st.exception(e)

        if st.session_state.metrics is not None:
            st.markdown("### Kết quả đánh giá mô hình")
            metrics = st.session_state.metrics
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Accuracy", f"{metrics['Accuracy']:.4f}"); c2.metric("Balanced Accuracy", f"{metrics['Balanced Accuracy']:.4f}")
            c3.metric("Precision", f"{metrics['Precision']:.4f}"); c4.metric("Recall", f"{metrics['Recall']:.4f}")
            c5, c6, c7 = st.columns(3)
            c5.metric("F1-score", f"{metrics['F1-score']:.4f}"); c6.metric("ROC-AUC", f"{metrics['ROC-AUC']:.4f}"); c7.metric("PR-AUC", f"{metrics['PR-AUC']:.4f}")
            st.markdown("### Cross-validation tổng quát"); st.dataframe(st.session_state.cv_summary, use_container_width=True)
            st.markdown("### Threshold Tuning"); st.dataframe(st.session_state.threshold_df, use_container_width=True)
            st.pyplot(plot_threshold_tuning(st.session_state.threshold_df, st.session_state.suggested_threshold), use_container_width=False)
            st.info(f"Ngưỡng gợi ý theo F1-score và Recall: {st.session_state.suggested_threshold:.2f}")
            st.markdown("### Error Analysis"); st.dataframe(st.session_state.error_summary, use_container_width=True)
            st.pyplot(plot_error_analysis(st.session_state.error_summary), use_container_width=False); st.pyplot(plot_error_probability_distribution(st.session_state.error_df), use_container_width=False)
            st.markdown("### Confusion Matrix"); st.pyplot(plot_confusion_matrix(st.session_state.cm), use_container_width=False)
            st.markdown("### Classification Report"); st.code(st.session_state.report)
            st.markdown("### Feature Importance")
            st.write(
                "Feature Importance cho biết các biến nào ảnh hưởng mạnh đến mô hình ở mức tổng quát. "
                "Khác với SHAP giải thích từng nhân viên, Feature Importance dùng để xem xu hướng chung của toàn bộ mô hình."
            )

            st.caption(
                f"Số feature thực tế được đưa vào mô hình: {len(st.session_state.feature_cols)}. "
                "Nếu số feature ít, hãy kiểm tra trạng thái feature ở phần Đặc tả Feature Engineering phía trên."
            )

            fig_imp, imp_df = plot_feature_importance(st.session_state.model, st.session_state.feature_cols, top_n=15)
            if fig_imp is None:
                st.info("Mô hình hiện tại không hỗ trợ Feature Importance trực tiếp.")
            else:
                if len(imp_df) <= 4:
                    st.warning(
                        "Feature Importance hiện chỉ có rất ít cột. Nguyên nhân thường gặp là các cột KPI bị NULL toàn bộ, "
                        "đặc biệt khi ngày dự đoán/lookback không khớp với khoảng dữ liệu KPI. Hãy kiểm tra bảng trạng thái feature ở trên."
                    )
                st.pyplot(fig_imp, use_container_width=False)
                st.dataframe(imp_df, use_container_width=True)

# ============================================================
# TAB 3 - NEW EMPLOYEE + SHAP
# ============================================================

with tab3:
    st.subheader("3. Dự đoán nhân viên mới và giải thích bằng SHAP")
    if st.session_state.df is None:
        st.warning("Bạn cần nạp dữ liệu SQL ở Tab 1 trước.")
    elif st.session_state.model is None:
        st.warning("Bạn cần huấn luyện mô hình ở Tab 2 trước.")
    else:
        df = st.session_state.df; model = st.session_state.model; feature_cols = st.session_state.feature_cols; medians = st.session_state.medians
        X_all = build_model_input(df, feature_cols, medians)
        st.markdown("### Thống kê dữ liệu huấn luyện để nhập đúng thang đo")
        profile_df = X_all.describe().T[["min", "25%", "50%", "75%", "max", "mean"]].reset_index().rename(columns={"index": "Feature"})
        st.dataframe(profile_df, use_container_width=True)
        input_df = create_new_employee_input_form(get_reference_values(df))
        st.markdown("### Dữ liệu nhân viên mới"); st.dataframe(input_df, use_container_width=True)
        if st.button("Dự đoán nhân viên mới", type="primary"):
            result_df, X_one = predict_with_model(model, input_df, feature_cols, medians, threshold)
            prob_exit = result_df["Exit_Probability"].iloc[0]; pred_label = int(result_df["Predicted_Is_Exit"].iloc[0]); risk_level = result_df["Risk_Level"].iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Xác suất nghỉ việc", f"{prob_exit:.2%}"); c2.metric("Nhãn dự đoán", "Nghỉ việc" if pred_label == 1 else "Ở lại"); c3.metric("Mức rủi ro", str(risk_level))
            st.markdown("### Dữ liệu sau Feature Engineering"); st.dataframe(X_one, use_container_width=True)
            st.markdown("### SHAP - Giải thích dự đoán nhân viên mới")
            st.write(
                "SHAP giải thích từng dự đoán bằng cách cho biết mỗi biến đầu vào đang làm tăng hay làm giảm nguy cơ nghỉ việc của nhân viên được chọn."
            )
            st.dataframe(get_shap_description(), use_container_width=True)
            if not SHAP_AVAILABLE: st.warning("Chưa cài thư viện SHAP. Hãy chạy: python -m pip install shap")
            else:
                with st.spinner("Đang tính SHAP..."):
                    explanation_df, error = make_local_explanation_df(model, X_all, X_one)
                if error is not None: st.error("Không tính được SHAP."); st.code(error)
                else:
                    st.dataframe(explanation_df[["Biến đầu vào", "Giá trị", "SHAP Value", "Tác động", "Mức độ ảnh hưởng"]].head(12), use_container_width=True)
                    st.pyplot(plot_local_shap_bar(explanation_df, top_n=10), use_container_width=False)

# ============================================================
# TAB 4 - DWH EMPLOYEE PREDICTION + SHAP
# ============================================================

with tab4:
    st.subheader("4. Dự đoán các nhân viên trong dữ liệu DWH/STG")
    if st.session_state.df is None:
        st.warning("Bạn cần nạp dữ liệu SQL ở Tab 1 trước.")
    elif st.session_state.model is None:
        st.warning("Bạn cần huấn luyện mô hình ở Tab 2 trước.")
    else:
        df = st.session_state.df; model = st.session_state.model; feature_cols = st.session_state.feature_cols; medians = st.session_state.medians
        st.info("Phần này áp dụng mô hình đã huấn luyện để dự đoán nguy cơ nghỉ việc cho toàn bộ nhân viên đang có trong dữ liệu SQL/DWH.")
        if st.button("Dự đoán toàn bộ nhân viên trong DWH", type="primary"):
            result_df, X_dwh = predict_with_model(model, df, feature_cols, medians, threshold)
            front = ["Employee_Id", "Is_Exit_Flag", "Exit_Probability", "Predicted_Is_Exit", "Predicted_Label", "Risk_Level"]
            result_df = result_df[[c for c in front if c in result_df.columns] + [c for c in result_df.columns if c not in front]]
            st.session_state.dwh_prediction_result = result_df
            st.success("Đã dự đoán toàn bộ nhân viên trong dữ liệu DWH/STG.")
        if st.session_state.dwh_prediction_result is not None:
            result_df = st.session_state.dwh_prediction_result
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tổng nhân viên", f"{len(result_df):,}"); c2.metric("Dự đoán nghỉ việc", f"{int(result_df['Predicted_Is_Exit'].sum()):,}")
            c3.metric("Xác suất TB", f"{result_df['Exit_Probability'].mean():.2%}"); c4.metric("Rủi ro cao", f"{int((result_df['Risk_Level'] == 'Cao').sum()):,}")
            fig_risk, risk_count_df = plot_risk_distribution(result_df); st.pyplot(fig_risk, use_container_width=False)
            st.markdown("### Bảng phân bố mức rủi ro"); st.dataframe(risk_count_df, use_container_width=True)
            st.markdown("### Top nhân viên có nguy cơ nghỉ việc cao nhất"); st.dataframe(result_df.sort_values("Exit_Probability", ascending=False).head(30), use_container_width=True)
            csv = result_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button("Tải kết quả dự đoán DWH CSV", data=csv, file_name="du_doan_nguy_co_nghi_viec_nhan_vien_dwh.csv", mime="text/csv")
            st.markdown("---"); st.markdown("### SHAP - Giải thích từng nhân viên trong DWH")
            st.write(
                "Chọn một nhân viên trong danh sách DWH/STG để xem các yếu tố làm tăng hoặc giảm xác suất nghỉ việc của riêng nhân viên đó."
            )
            st.dataframe(get_shap_description(), use_container_width=True)
            employee_ids = result_df["Employee_Id"].astype(str).tolist()
            selected_employee = st.selectbox("Chọn nhân viên cần giải thích", employee_ids)
            selected_row = df[df["Employee_Id"].astype(str) == str(selected_employee)].copy()
            if selected_row.empty: st.warning("Không tìm thấy nhân viên trong dữ liệu gốc.")
            else:
                selected_prediction = result_df[result_df["Employee_Id"].astype(str) == str(selected_employee)].copy()
                st.markdown("#### Kết quả dự đoán của nhân viên được chọn")
                st.dataframe(selected_prediction[[c for c in ["Employee_Id", "Is_Exit_Flag", "Exit_Probability", "Predicted_Label", "Risk_Level"] if c in selected_prediction.columns]], use_container_width=True)
                if st.button("Giải thích nhân viên DWH bằng SHAP", type="secondary"):
                    if not SHAP_AVAILABLE: st.warning("Chưa cài thư viện SHAP. Hãy chạy: python -m pip install shap")
                    else:
                        X_background = build_model_input(df, feature_cols, medians); X_one = build_model_input(selected_row, feature_cols, medians)
                        with st.spinner("Đang tính SHAP cho nhân viên được chọn..."):
                            explanation_df, error = make_local_explanation_df(model, X_background, X_one)
                        if error is not None: st.error("Không tính được SHAP."); st.code(error)
                        else:
                            st.dataframe(explanation_df[["Biến đầu vào", "Giá trị", "SHAP Value", "Tác động", "Mức độ ảnh hưởng"]].head(12), use_container_width=True)
                            st.pyplot(plot_local_shap_bar(explanation_df, top_n=10), use_container_width=False)

# ============================================================
# TAB 5 - BATCH CSV
# ============================================================

with tab5:
    st.subheader("5. Dự đoán hàng loạt bằng CSV nhân viên mới")
    if st.session_state.df is None:
        st.warning("Bạn cần nạp dữ liệu SQL ở Tab 1 trước.")
    elif st.session_state.model is None:
        st.warning("Bạn cần huấn luyện mô hình ở Tab 2 trước.")
    else:
        df = st.session_state.df; model = st.session_state.model; feature_cols = st.session_state.feature_cols; medians = st.session_state.medians
        template_df = create_template_csv(get_reference_values(df)); template_csv = template_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("Tải file mẫu CSV nhân viên mới", data=template_csv, file_name="mau_nhan_vien_moi_du_doan_nghi_viec.csv", mime="text/csv")
        uploaded_csv = st.file_uploader("Upload file CSV nhân viên mới", type=["csv"])
        if uploaded_csv is not None:
            try:
                new_df = pd.read_csv(uploaded_csv)
                st.markdown("### Dữ liệu đã upload"); st.dataframe(new_df.head(30), use_container_width=True)
                missing = [c for c in BASE_FEATURE_COLS if c not in new_df.columns]
                if missing: st.error("File CSV thiếu các cột sau: " + ", ".join(missing))
                else:
                    if st.button("Dự đoán hàng loạt CSV", type="primary"):
                        result_df, X_new = predict_with_model(model, new_df, feature_cols, medians, threshold)
                        st.session_state.batch_result = result_df; st.success("Dự đoán hàng loạt thành công.")
            except Exception as e:
                st.error("Không đọc được file CSV."); st.exception(e)
        if st.session_state.batch_result is not None:
            result_df = st.session_state.batch_result
            st.markdown("### Kết quả dự đoán hàng loạt"); st.dataframe(result_df, use_container_width=True)
            csv = result_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button("Tải kết quả CSV", data=csv, file_name="du_doan_nguy_co_nghi_viec_hang_loat.csv", mime="text/csv")
