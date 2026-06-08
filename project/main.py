# project/main.py
from etl.extract import read_excel_sheets, list_sheets_and_columns
from etl.profile import profile_all
from etl.transform import transform_all
from etl.load_sqlserver import load_all_staging
from etl.build_dwh import build_database_objects, load_dimensions_and_facts

def main():
    print("1) Extract dữ liệu từ Excel...")
    data = read_excel_sheets()

    print("2) Liệt kê sheet/cột...")
    info = list_sheets_and_columns()
    for item in info:
        print(item)

    print("3) Profile dữ liệu...")
    report = profile_all(data)
    for k, v in report.items():
        print(k, v["row_count"], v["col_count"])

    print("4) Transform dữ liệu...")
    transformed = transform_all(data)

    print("5) Tạo schemas/tables SQL Server...")
    build_database_objects()

    print("6) Load staging...")
    engine = load_all_staging(transformed)

    print("7) Load dimensions & facts...")
    load_dimensions_and_facts()

    print("Hoàn tất ETL + DWH.")

if __name__ == "__main__":
    main()