# load_sqlserver.py
# Chức năng:
# - Tạo kết nối tới SQL Server bằng SQLAlchemy.
# - Thực thi các script SQL trong thư mục sql/.
# - Nạp dữ liệu đã transform từ pandas DataFrame vào schema staging.
# - Ép toàn bộ cột text thành NVARCHAR để không lỗi tiếng Việt.
# - Hỗ trợ load dữ liệu lớn bằng chunksize.
# - Tắt insertmanyvalues và bật fast_executemany để tối ưu khi dùng pyodbc/SQL Server.

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.mssql import NVARCHAR
from etl.config import CONN_STR


def get_engine():
    return create_engine(
        CONN_STR,
        fast_executemany=True,
        use_insertmanyvalues=False
    )


def execute_sql_file(engine, file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        sql = f.read()

    batches = sql.split("GO")

    with engine.begin() as conn:
        for batch in batches:
            batch = batch.strip()
            if batch:
                conn.execute(text(batch))


def load_to_staging(
    engine,
    df: pd.DataFrame,
    table_name: str,
    schema: str = "stg",
    if_exists: str = "replace"
):
    print(f"Loading {schema}.{table_name}: rows={len(df)}, cols={len(df.columns)}")

    # Debug nhanh để kiểm tra Python còn giữ đúng tiếng Việt không
    if table_name == "employees" and "Full_Name" in df.columns:
        print("DEBUG tiếng Việt trước khi load SQL:")
        print(df[["Employee_Id", "Full_Name", "Education_Level", "Employment_Type"]].head(5))

    if table_name == "stores" and "Store_Name" in df.columns:
        print("DEBUG stores trước khi load SQL:")
        print(df[["Store_Id", "Store_Name", "City", "Store_Type"]].head(5))

    # Ép tất cả cột dạng text thành NVARCHAR
    text_cols = df.select_dtypes(
        include=["object", "string", "category"]
    ).columns.tolist()

    dtype_map = {
        col: NVARCHAR(length=500)
        for col in text_cols
    }

    df.to_sql(
        name=table_name,
        con=engine,
        schema=schema,
        if_exists=if_exists,
        index=False,
        chunksize=50,
        dtype=dtype_map
    )


def load_all_staging(transformed: dict):
    engine = get_engine()

    load_to_staging(engine, transformed["employees"], "employees")
    load_to_staging(engine, transformed["stores"], "stores")
    load_to_staging(engine, transformed["monthly_performance"], "monthly_performance")
    load_to_staging(engine, transformed["role_kpis_long"], "role_kpis_long")
    load_to_staging(engine, transformed["business_outcomes"], "business_outcomes")
    load_to_staging(engine, transformed["dim_date"], "dim_date")
    load_to_staging(engine, transformed["data_dictionary"], "data_dictionary")

    return engine