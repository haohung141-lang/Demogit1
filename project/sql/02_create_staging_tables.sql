-- Có thể để trống nếu dùng pandas.to_sql replace
-- Tạo hoặc chuẩn bị các bảng staging.
-- Staging là tầng trung gian lưu dữ liệu sau khi Python đã extract và transform.
-- Các bảng staging thường tương ứng với dữ liệu nguồn như employees, stores, monthly_performance,...
-- Dữ liệu trong staging sẽ được dùng làm nguồn để nạp sang các bảng Dimension và Fact.
-- bước trung gian giữa dữ liệu thô và Data Warehouse.
SELECT 1;
GO
