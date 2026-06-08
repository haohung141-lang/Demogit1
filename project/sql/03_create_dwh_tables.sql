--Tạo các bảng trong Data Warehouse.
-- File này tạo các bảng Dimension như DimEmployee, DimStore, DimDate, DimDepartment,...
-- Đồng thời tạo các bảng Fact như FactEmployeeMonthlyPerformance, FactRoleKpis, FactBusinessOutcomes.
-- Các bảng Dimension lưu thông tin mô tả đối tượng phân tích.
-- Các bảng Fact lưu dữ liệu đo lường, chỉ số hiệu suất, KPI và kết quả kinh doanh.
-- Đây là phần xây dựng mô hình dữ liệu dạng Star Schema cho hệ thống phân tích

-- DROP FACT TABLES TRƯỚC
IF OBJECT_ID('dwh.FactEmployeeMonthlyPerformance', 'U') IS NOT NULL 
    DROP TABLE dwh.FactEmployeeMonthlyPerformance;

IF OBJECT_ID('dwh.FactRoleKpis', 'U') IS NOT NULL 
    DROP TABLE dwh.FactRoleKpis;

IF OBJECT_ID('dwh.FactBusinessOutcomes', 'U') IS NOT NULL 
    DROP TABLE dwh.FactBusinessOutcomes;

-- DROP DIM EMPLOYEE NGAY SAU FACT
IF OBJECT_ID('dwh.DimEmployee', 'U') IS NOT NULL 
    DROP TABLE dwh.DimEmployee;

-- DROP CÁC DIMENSIONS CÒN LẠI
IF OBJECT_ID('dwh.DimKpi', 'U') IS NOT NULL 
    DROP TABLE dwh.DimKpi;

IF OBJECT_ID('dwh.DimDepartment', 'U') IS NOT NULL 
    DROP TABLE dwh.DimDepartment;

IF OBJECT_ID('dwh.DimJobRole', 'U') IS NOT NULL 
    DROP TABLE dwh.DimJobRole;

IF OBJECT_ID('dwh.DimJobLevel', 'U') IS NOT NULL 
    DROP TABLE dwh.DimJobLevel;

IF OBJECT_ID('dwh.DimManager', 'U') IS NOT NULL 
    DROP TABLE dwh.DimManager;

IF OBJECT_ID('dwh.DimStore', 'U') IS NOT NULL 
    DROP TABLE dwh.DimStore;

IF OBJECT_ID('dwh.DimDate', 'U') IS NOT NULL 
    DROP TABLE dwh.DimDate;
GO
GO

CREATE TABLE dwh.DimDepartment (
    DepartmentKey INT IDENTITY(1,1) PRIMARY KEY,
    DepartmentName NVARCHAR(200) NOT NULL UNIQUE
);
GO

CREATE TABLE dwh.DimJobRole (
    JobRoleKey INT IDENTITY(1,1) PRIMARY KEY,
    JobRoleName NVARCHAR(200) NOT NULL UNIQUE
);
GO

CREATE TABLE dwh.DimJobLevel (
    JobLevelKey INT IDENTITY(1,1) PRIMARY KEY,
    JobLevelName NVARCHAR(200) NOT NULL UNIQUE
);
GO

CREATE TABLE dwh.DimManager (
    ManagerKey INT IDENTITY(1,1) PRIMARY KEY,
    Manager_Id NVARCHAR(50) NOT NULL,
    Manager_Name NVARCHAR(200) NULL,
    Manager_Status NVARCHAR(100) NULL,
    CONSTRAINT UQ_DimManager UNIQUE (Manager_Id)
);
GO

CREATE TABLE dwh.DimStore (
    StoreKey INT IDENTITY(1,1) PRIMARY KEY,
    Store_Id NVARCHAR(50) NOT NULL,
    Store_Name NVARCHAR(200) NULL,
    City NVARCHAR(100) NULL,
    City_Latitude DECIMAL(18,6) NULL,
    City_Longitude DECIMAL(18,6) NULL,
    Store_Type NVARCHAR(100) NULL,
    Opening_Date DATE NULL,
    CONSTRAINT UQ_DimStore UNIQUE (Store_Id)
);
GO

CREATE TABLE dwh.DimKpi (
    KpiKey INT IDENTITY(1,1) PRIMARY KEY,
    KpiName NVARCHAR(200) NOT NULL UNIQUE
);
GO

CREATE TABLE dwh.DimDate (
    DateKey INT PRIMARY KEY,
    FullDate DATE NOT NULL,
    [Year] INT NOT NULL,
    [Quarter] INT NOT NULL,
    [Month] INT NOT NULL,
    MonthName NVARCHAR(20) NOT NULL,
    YearMonth CHAR(7) NOT NULL,
    MonthStartDate DATE NOT NULL,
    MonthEndDate DATE NOT NULL
);
GO

CREATE TABLE dwh.DimEmployee (
    EmployeeKey INT IDENTITY(1,1) PRIMARY KEY,
    Employee_Id NVARCHAR(50) NOT NULL,
    Full_Name NVARCHAR(200) NULL,
    Age INT NULL,
    Education_Level NVARCHAR(100) NULL,
    Employment_Type NVARCHAR(100) NULL,
    Base_Salary_Annual DECIMAL(18,2) NULL,
    Salary_Band NVARCHAR(50) NULL,
    Hire_Date DATE NULL,
    Exit_Date DATE NULL,
    Is_Exit_Flag BIT NOT NULL DEFAULT 0,
    Tenure_Months INT NULL,
    DepartmentKey INT NULL,
    JobRoleKey INT NULL,
    JobLevelKey INT NULL,
    StoreKey INT NULL,
    ManagerKey INT NULL,
    Effective_From DATE NOT NULL,
    Effective_To DATE NOT NULL,
    Is_Current BIT NOT NULL,
    HashDiff VARBINARY(32) NULL,

    CONSTRAINT FK_DimEmployee_Department FOREIGN KEY (DepartmentKey) REFERENCES dwh.DimDepartment(DepartmentKey),
    CONSTRAINT FK_DimEmployee_JobRole FOREIGN KEY (JobRoleKey) REFERENCES dwh.DimJobRole(JobRoleKey),
    CONSTRAINT FK_DimEmployee_JobLevel FOREIGN KEY (JobLevelKey) REFERENCES dwh.DimJobLevel(JobLevelKey),
    CONSTRAINT FK_DimEmployee_Store FOREIGN KEY (StoreKey) REFERENCES dwh.DimStore(StoreKey),
    CONSTRAINT FK_DimEmployee_Manager FOREIGN KEY (ManagerKey) REFERENCES dwh.DimManager(ManagerKey)
);
GO

CREATE TABLE dwh.FactEmployeeMonthlyPerformance (
    FactEmployeeMonthlyPerformanceKey BIGINT IDENTITY(1,1) PRIMARY KEY,
    EmployeeKey INT NOT NULL,
    DateKey INT NOT NULL,
    Performance_Rating DECIMAL(10,2) NOT NULL,
    Training_Hours INT NOT NULL,
    Overtime_Hours INT NOT NULL,
    Absenteeism_Days INT NOT NULL,
    Promotion_Flag BIT NOT NULL,
    Salary_Increase_Flag BIT NOT NULL,
    Monthly_Bonus DECIMAL(18,2) NOT NULL,
    Benefits_Cost DECIMAL(18,2) NOT NULL,
    Employee_Satisfaction DECIMAL(10,2) NOT NULL,
    Engagement_Index DECIMAL(10,2) NOT NULL,
    Manager_Evaluation DECIMAL(10,2) NOT NULL,

    CONSTRAINT FK_FEMP_Employee FOREIGN KEY (EmployeeKey) REFERENCES dwh.DimEmployee(EmployeeKey),
    CONSTRAINT FK_FEMP_Date FOREIGN KEY (DateKey) REFERENCES dwh.DimDate(DateKey)
);
GO

CREATE TABLE dwh.FactRoleKpis (
    FactRoleKpisKey BIGINT IDENTITY(1,1) PRIMARY KEY,
    EmployeeKey INT NOT NULL,
    DateKey INT NOT NULL,
    KpiKey INT NOT NULL,
    Kpi_Value DECIMAL(18,4) NOT NULL,
    Productivity_Index DECIMAL(18,4) NOT NULL,

    CONSTRAINT FK_FRK_Employee FOREIGN KEY (EmployeeKey) REFERENCES dwh.DimEmployee(EmployeeKey),
    CONSTRAINT FK_FRK_Date FOREIGN KEY (DateKey) REFERENCES dwh.DimDate(DateKey),
    CONSTRAINT FK_FRK_Kpi FOREIGN KEY (KpiKey) REFERENCES dwh.DimKpi(KpiKey)
);
GO

CREATE TABLE dwh.FactBusinessOutcomes (
    FactBusinessOutcomesKey BIGINT IDENTITY(1,1) PRIMARY KEY,
    StoreKey INT NOT NULL,
    DepartmentKey INT NOT NULL,
    DateKey INT NOT NULL,
    Sales_Target DECIMAL(18,2) NOT NULL,
    Sales_Actual DECIMAL(18,2) NOT NULL,
    Customer_Satisfaction DECIMAL(10,2) NOT NULL,
    Nps_Score DECIMAL(10,2) NOT NULL,
    Waste_Percentage DECIMAL(10,4) NOT NULL,
    On_Time_Delivery DECIMAL(10,2) NOT NULL,

    CONSTRAINT FK_FBO_Store FOREIGN KEY (StoreKey) REFERENCES dwh.DimStore(StoreKey),
    CONSTRAINT FK_FBO_Department FOREIGN KEY (DepartmentKey) REFERENCES dwh.DimDepartment(DepartmentKey),
    CONSTRAINT FK_FBO_Date FOREIGN KEY (DateKey) REFERENCES dwh.DimDate(DateKey)
);
GO