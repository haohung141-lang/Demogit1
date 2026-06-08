# project/etl/extract.py
# - Đọc file Excel đầu vào.
# - Lấy danh sách các sheet trong file.
# - Đọc dữ liệu từng sheet thành pandas DataFrame.
# - Trả dữ liệu về dạng dictionary để các bước sau xử lý.

# - Cung cấp thông tin cơ bản như tên sheet, số dòng, số cột, danh sách cột.
# File này chưa xử lý dữ liệu sâu, chỉ tập trung vào việc trích xuất dữ liệu nguồn.


import pandas as pd
from openpyxl import load_workbook
from etl.config import DATA_FILE

def read_excel_sheets():
    """
    Đọc toàn bộ sheet từ file Excel nguồn.
    """
    xls = pd.ExcelFile(DATA_FILE, engine="openpyxl")
    data = {}
    for sheet in xls.sheet_names:
        data[sheet] = pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")
    return data

def list_sheets_and_columns():
    xls = pd.ExcelFile(DATA_FILE, engine="openpyxl")
    info = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(DATA_FILE, sheet_name=sheet, engine="openpyxl")
        info.append({
            "sheet_name": sheet,
            "row_count": int(df.shape[0]),
            "col_count": int(df.shape[1]),
            "columns": list(df.columns)
        })
    return info

if __name__ == "__main__":
    info = list_sheets_and_columns()
    for item in info:
        print("=" * 100)
        print(item["sheet_name"])
        print("rows:", item["row_count"], "cols:", item["col_count"])
        print(item["columns"])