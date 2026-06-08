
-- Chức năng: Tạo các schema cần thiết trong SQL Server.
-- tạo schema staging từ Excel.--tạo schema staging (stg) và data warehouse (dwh).
-- Schema dwh dùng để lưu các bảng Dimension và Fact của Data Warehouse.
-- khởi tạo cấu trúc database trước khi tạo bảng.

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'stg')
    EXEC('CREATE SCHEMA stg');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dwh')
    EXEC('CREATE SCHEMA dwh');
GO