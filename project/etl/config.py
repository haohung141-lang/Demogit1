# project/etl/config.py
# File cấu hình kết nối SQL Server cho project.
# CONN_STR là chuỗi kết nối được dùng bởi SQLAlchemy/pyodbc.
# Dùng để kết nối tới database HRAnalyticsDW.
# Các module như load_sqlserver.py, build_dwh.py, ML hoặc Streamlit sẽ dùng cấu hình này.
# Khi thay đổi server, database hoặc driver, chỉ cần cập nhật tại đây.

CONN_STR = (
    "mssql+pyodbc://@localhost\\SQLEXPRESS/HRAnalyticsDW"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
)
from urllib.parse import quote_plus

DATA_FILE = "project/data/Employee Performance Dataset.xlsx"

params = quote_plus(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=HUYLEE\\SQLEXPRESS;"
    "DATABASE=HRAnalyticsDW;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

CONN_STR = f"mssql+pyodbc:///?odbc_connect={params}"