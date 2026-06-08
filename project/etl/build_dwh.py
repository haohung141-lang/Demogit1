# project/etl/build_dwh.py
#build_dwh.py dùng để xây dựng cấu trúc Data Warehouse trong SQL Server.
#Gọi kết nối sql server
#Tạo schema
#Tạo bảng
#Load dữ liệu từ staging sang Data Warehouse
#Tạo lại DWH mỗi lần chạy ETL
from pathlib import Path
from etl.load_sqlserver import get_engine, execute_sql_file

BASE_SQL = Path(__file__).resolve().parents[1] / "sql"

def build_database_objects():
    engine = get_engine()
    execute_sql_file(engine, str(BASE_SQL / "01_create_schemas.sql"))
    execute_sql_file(engine, str(BASE_SQL / "02_create_staging_tables.sql"))
    execute_sql_file(engine, str(BASE_SQL / "03_create_dwh_tables.sql"))

def load_dimensions_and_facts():
    engine = get_engine()
    execute_sql_file(engine, str(BASE_SQL / "04_merge_dimensions.sql"))
    execute_sql_file(engine, str(BASE_SQL / "05_load_facts.sql"))