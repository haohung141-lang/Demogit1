# export_after_etl_full.py
# -*- coding: utf-8 -*-

import urllib
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine


# ============================================================
# 1. CAU HINH SQL SERVER
# ============================================================

SERVER = r"HUYLEE\SQLEXPRESS"   # sua lai neu server cua ban khac
DATABASE = "HRAnalyticsDW"
DRIVER = "ODBC Driver 17 for SQL Server"

OUTPUT_FILE = "exports/etl_output_stg_dwh_full.xlsx"

EXCEL_MAX_ROWS = 1_048_576


STG_TABLES = [
    "employees",
    "stores",
    "monthly_performance",
    "role_kpis_long",
    "business_outcomes",
    "dim_date",
    "data_dictionary",
]


DWH_TABLES = [
    "DimEmployee",
    "DimDepartment",
    "DimJobRole",
    "DimJobLevel",
    "DimManager",
    "DimStore",
    "DimKpi",
    "DimDate",
    "FactEmployeeMonthlyPerformance",
    "FactRoleKpis",
    "FactBusinessOutcomes",
]


# ============================================================
# 2. TAO KET NOI SQL SERVER
# ============================================================

def create_sql_engine():
    params = urllib.parse.quote_plus(
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    conn_str = f"mssql+pyodbc:///?odbc_connect={params}"
    return create_engine(conn_str)


# ============================================================
# 3. HAM HO TRO
# ============================================================

def safe_sheet_name(name: str) -> str:
    invalid_chars = ["\\", "/", "*", "?", ":", "[", "]"]

    sheet_name = str(name)

    for ch in invalid_chars:
        sheet_name = sheet_name.replace(ch, "_")

    return sheet_name[:31]


def read_table(engine, schema_name: str, table_name: str):
    query = f"SELECT * FROM {schema_name}.{table_name}"
    df = pd.read_sql(query, con=engine)
    return df


def get_table_count(engine, schema_name: str, table_name: str):
    query = f"SELECT COUNT(*) AS RowCount FROM {schema_name}.{table_name}"
    df = pd.read_sql(query, con=engine)
    return int(df.loc[0, "RowCount"])


def write_df_to_excel(writer, df: pd.DataFrame, sheet_name: str):
    clean_sheet_name = safe_sheet_name(sheet_name)

    if len(df) > EXCEL_MAX_ROWS:
        part = 1

        for start in range(0, len(df), EXCEL_MAX_ROWS):
            end = start + EXCEL_MAX_ROWS
            df_part = df.iloc[start:end]

            part_sheet_name = safe_sheet_name(f"{clean_sheet_name}_{part}")
            df_part.to_excel(writer, sheet_name=part_sheet_name, index=False)

            part += 1
    else:
        df.to_excel(writer, sheet_name=clean_sheet_name, index=False)


# ============================================================
# 4. XUAT EXCEL SAU ETL
# ============================================================

def export_after_etl():
    engine = create_sql_engine()

    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_rows = []

    print("============================================================")
    print("BAT DAU XUAT FILE EXCEL SAU ETL")
    print("============================================================")
    print(f"Database: {DATABASE}")
    print(f"Output  : {output_path}")
    print("============================================================")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        # ------------------------------------------------------------
        # README
        # ------------------------------------------------------------

        readme_df = pd.DataFrame(
            {
                "Noi dung": [
                    "File nay duoc xuat sau qua trinh ETL.",
                    "Nhom STG la du lieu da duoc xu ly va nap vao schema staging.",
                    "Nhom DWH la du lieu da duoc to chuc thanh Dimension va Fact trong Data Warehouse.",
                    "STG dung de kiem tra du lieu trung gian sau ETL.",
                    "DWH dung de phuc vu Power BI Dashboard va phan tich du lieu.",
                    "File nay khong phai du lieu tho ban dau.",
                    "Thoi diem xuat file: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            }
        )

        readme_df.to_excel(writer, sheet_name="README_ETL", index=False)

        # ------------------------------------------------------------
        # EXPORT STAGING
        # ------------------------------------------------------------

        for table in STG_TABLES:
            schema_name = "stg"
            full_name = f"{schema_name}.{table}"

            try:
                print(f"[INFO] Dang doc bang: {full_name}")

                df = read_table(engine, schema_name, table)

                print(f"       So dong: {len(df):,} | So cot: {df.shape[1]:,}")

                sheet_name = f"STG_{table}"
                write_df_to_excel(writer, df, sheet_name)

                summary_rows.append(
                    {
                        "Schema": schema_name,
                        "Table": table,
                        "Sheet": safe_sheet_name(sheet_name),
                        "Rows": len(df),
                        "Columns": df.shape[1],
                        "Ghi_chu": "Du lieu staging sau ETL",
                    }
                )

            except Exception as e:
                print(f"[WARNING] Khong xuat duoc bang {full_name}")
                print(f"          Loi: {e}")

                summary_rows.append(
                    {
                        "Schema": schema_name,
                        "Table": table,
                        "Sheet": "",
                        "Rows": None,
                        "Columns": None,
                        "Ghi_chu": f"Loi: {e}",
                    }
                )

        # ------------------------------------------------------------
        # EXPORT DATA WAREHOUSE
        # ------------------------------------------------------------

        for table in DWH_TABLES:
            schema_name = "dwh"
            full_name = f"{schema_name}.{table}"

            try:
                print(f"[INFO] Dang doc bang: {full_name}")

                df = read_table(engine, schema_name, table)

                print(f"       So dong: {len(df):,} | So cot: {df.shape[1]:,}")

                sheet_name = f"DWH_{table}"
                write_df_to_excel(writer, df, sheet_name)

                summary_rows.append(
                    {
                        "Schema": schema_name,
                        "Table": table,
                        "Sheet": safe_sheet_name(sheet_name),
                        "Rows": len(df),
                        "Columns": df.shape[1],
                        "Ghi_chu": "Du lieu Data Warehouse sau ETL",
                    }
                )

            except Exception as e:
                print(f"[WARNING] Khong xuat duoc bang {full_name}")
                print(f"          Loi: {e}")

                summary_rows.append(
                    {
                        "Schema": schema_name,
                        "Table": table,
                        "Sheet": "",
                        "Rows": None,
                        "Columns": None,
                        "Ghi_chu": f"Loi: {e}",
                    }
                )

        # ------------------------------------------------------------
        # SUMMARY
        # ------------------------------------------------------------

        summary_df = pd.DataFrame(summary_rows)

        summary_df.to_excel(writer, sheet_name="SUMMARY", index=False)

    print("============================================================")
    print("[SUCCESS] DA XUAT FILE EXCEL SAU ETL THANH CONG")
    print(f"File duoc luu tai: {output_path}")
    print("============================================================")


# ============================================================
# 5. MAIN
# ============================================================

if __name__ == "__main__":
    export_after_etl()