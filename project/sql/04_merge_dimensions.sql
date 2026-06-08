
-- Nạp dữ liệu từ staging vào các bảng Dimension.
-- lấy dữ liệu đã xử lý trong schema stg để insert/merge vào schema dwh.
-- Các bảng được nạp gồm DimEmployee, DimStore, DimDate, DimDepartment, DimJobRole, DimJobLevel, DimManager, DimKpi.
-- Mục tiêu là chuẩn hóa dữ liệu mô tả và tạo khóa thay thế cho các Dimension.
-- Chuẩn bị dữ liệu nền để các bảng Fact có thể tham chiếu bằng khóa ngoại.
-- 1) DimDepartment
INSERT INTO dwh.DimDepartment (DepartmentName)
SELECT DISTINCT Department
FROM (
    SELECT Department FROM stg.employees
    UNION
    SELECT Department FROM stg.business_outcomes
) x
WHERE Department IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM dwh.DimDepartment d
      WHERE d.DepartmentName = x.Department
  );
GO

-- 2) DimJobRole
INSERT INTO dwh.DimJobRole (JobRoleName)
SELECT DISTINCT Job_Role
FROM stg.employees s
WHERE Job_Role IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dwh.DimJobRole d WHERE d.JobRoleName = s.Job_Role
  );
GO

-- 3) DimJobLevel
INSERT INTO dwh.DimJobLevel (JobLevelName)
SELECT DISTINCT Job_Level
FROM stg.employees s
WHERE Job_Level IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dwh.DimJobLevel d WHERE d.JobLevelName = s.Job_Level
  );
GO

-- 4) DimManager
INSERT INTO dwh.DimManager (Manager_Id, Manager_Name, Manager_Status)
SELECT DISTINCT Manager_Id, Manager_Name, Manager_Status
FROM stg.employees s
WHERE Manager_Id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dwh.DimManager d WHERE d.Manager_Id = s.Manager_Id
  );
GO

-- 5) DimStore
INSERT INTO dwh.DimStore (Store_Id, Store_Name, City, City_Latitude, City_Longitude, Store_Type, Opening_Date)
SELECT s.Store_Id, s.Store_Name, s.City, s.City_Latitude, s.City_Longitude, s.Store_Type, s.Opening_Date
FROM stg.stores s
WHERE NOT EXISTS (
    SELECT 1 FROM dwh.DimStore d WHERE d.Store_Id = s.Store_Id
);
GO

-- 6) DimKpi
INSERT INTO dwh.DimKpi (KpiName)
SELECT DISTINCT Kpi_Name
FROM stg.role_kpis_long s
WHERE Kpi_Name IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dwh.DimKpi d WHERE d.KpiName = s.Kpi_Name
  );
GO

-- 7) DimDate
INSERT INTO dwh.DimDate (DateKey, FullDate, [Year], [Quarter], [Month], MonthName, YearMonth, MonthStartDate, MonthEndDate)
SELECT DateKey, FullDate, [Year], [Quarter], [Month], MonthName, YearMonth, MonthStartDate, MonthEndDate
FROM stg.dim_date s
WHERE NOT EXISTS (
    SELECT 1 FROM dwh.DimDate d WHERE d.DateKey = s.DateKey
);
GO

-- 8) DimEmployee - SCD Type 2 simplified
;WITH src AS (
    SELECT
        e.Employee_Id,
        e.Full_Name,
        e.Age,
        e.Education_Level,
        e.Employment_Type,
        CAST(e.Base_Salary_Annual AS DECIMAL(18,2)) AS Base_Salary_Annual,
        e.Salary_Band,
        CAST(e.Hire_Date AS DATE) AS Hire_Date,
        CAST(e.Exit_Date AS DATE) AS Exit_Date,
        CAST(e.Is_Exit_Flag AS BIT) AS Is_Exit_Flag,
        e.Tenure_Months,
        dd.DepartmentKey,
        jr.JobRoleKey,
        jl.JobLevelKey,
        ds.StoreKey,
        dm.ManagerKey,
        HASHBYTES(
            'SHA2_256',
            CONCAT(
                ISNULL(e.Full_Name, ''), '|',
                ISNULL(CAST(e.Age AS NVARCHAR(20)), ''), '|',
                ISNULL(e.Education_Level, ''), '|',
                ISNULL(e.Employment_Type, ''), '|',
                ISNULL(CAST(e.Base_Salary_Annual AS NVARCHAR(50)), ''), '|',
                ISNULL(e.Salary_Band, ''), '|',
                ISNULL(CONVERT(NVARCHAR(10), e.Hire_Date, 120), ''), '|',
                ISNULL(CONVERT(NVARCHAR(10), e.Exit_Date, 120), ''), '|',
                ISNULL(CAST(e.Is_Exit_Flag AS NVARCHAR(5)), ''), '|',
                ISNULL(CAST(e.Tenure_Months AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(dd.DepartmentKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(jr.JobRoleKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(jl.JobLevelKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(ds.StoreKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(dm.ManagerKey AS NVARCHAR(20)), '')
            )
        ) AS HashDiff
    FROM stg.employees e
    LEFT JOIN dwh.DimDepartment dd ON dd.DepartmentName = e.Department
    LEFT JOIN dwh.DimJobRole jr ON jr.JobRoleName = e.Job_Role
    LEFT JOIN dwh.DimJobLevel jl ON jl.JobLevelName = e.Job_Level
    LEFT JOIN dwh.DimStore ds ON ds.Store_Id = e.Store_Id
    LEFT JOIN dwh.DimManager dm ON dm.Manager_Id = e.Manager_Id
),
chg AS (
    SELECT s.*
    FROM src s
    LEFT JOIN dwh.DimEmployee d
      ON d.Employee_Id = s.Employee_Id
     AND d.Is_Current = 1
    WHERE d.EmployeeKey IS NULL
       OR d.HashDiff <> s.HashDiff
)
-- Close current rows if changed
UPDATE d
   SET d.Effective_To = CAST(GETDATE() AS DATE),
       d.Is_Current = 0
FROM dwh.DimEmployee d
JOIN chg s
  ON d.Employee_Id = s.Employee_Id
 AND d.Is_Current = 1;
GO

;WITH src AS (
    SELECT
        e.Employee_Id,
        e.Full_Name,
        e.Age,
        e.Education_Level,
        e.Employment_Type,
        CAST(e.Base_Salary_Annual AS DECIMAL(18,2)) AS Base_Salary_Annual,
        e.Salary_Band,
        CAST(e.Hire_Date AS DATE) AS Hire_Date,
        CAST(e.Exit_Date AS DATE) AS Exit_Date,
        CAST(e.Is_Exit_Flag AS BIT) AS Is_Exit_Flag,
        e.Tenure_Months,
        dd.DepartmentKey,
        jr.JobRoleKey,
        jl.JobLevelKey,
        ds.StoreKey,
        dm.ManagerKey,
        HASHBYTES(
            'SHA2_256',
            CONCAT(
                ISNULL(e.Full_Name, ''), '|',
                ISNULL(CAST(e.Age AS NVARCHAR(20)), ''), '|',
                ISNULL(e.Education_Level, ''), '|',
                ISNULL(e.Employment_Type, ''), '|',
                ISNULL(CAST(e.Base_Salary_Annual AS NVARCHAR(50)), ''), '|',
                ISNULL(e.Salary_Band, ''), '|',
                ISNULL(CONVERT(NVARCHAR(10), e.Hire_Date, 120), ''), '|',
                ISNULL(CONVERT(NVARCHAR(10), e.Exit_Date, 120), ''), '|',
                ISNULL(CAST(e.Is_Exit_Flag AS NVARCHAR(5)), ''), '|',
                ISNULL(CAST(e.Tenure_Months AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(dd.DepartmentKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(jr.JobRoleKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(jl.JobLevelKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(ds.StoreKey AS NVARCHAR(20)), ''), '|',
                ISNULL(CAST(dm.ManagerKey AS NVARCHAR(20)), '')
            )
        ) AS HashDiff
    FROM stg.employees e
    LEFT JOIN dwh.DimDepartment dd ON dd.DepartmentName = e.Department
    LEFT JOIN dwh.DimJobRole jr ON jr.JobRoleName = e.Job_Role
    LEFT JOIN dwh.DimJobLevel jl ON jl.JobLevelName = e.Job_Level
    LEFT JOIN dwh.DimStore ds ON ds.Store_Id = e.Store_Id
    LEFT JOIN dwh.DimManager dm ON dm.Manager_Id = e.Manager_Id
),
chg AS (
    SELECT s.*
    FROM src s
    LEFT JOIN dwh.DimEmployee d
      ON d.Employee_Id = s.Employee_Id
     AND d.Is_Current = 1
    WHERE d.EmployeeKey IS NULL
       OR d.HashDiff <> s.HashDiff
)
INSERT INTO dwh.DimEmployee (
    Employee_Id, Full_Name, Age, Education_Level, Employment_Type,
    Base_Salary_Annual, Salary_Band, Hire_Date, Exit_Date, Is_Exit_Flag,
    Tenure_Months, DepartmentKey, JobRoleKey, JobLevelKey, StoreKey, ManagerKey,
    Effective_From, Effective_To, Is_Current, HashDiff
)
SELECT
    Employee_Id, Full_Name, Age, Education_Level, Employment_Type,
    Base_Salary_Annual, Salary_Band, Hire_Date, Exit_Date, Is_Exit_Flag,
    Tenure_Months, DepartmentKey, JobRoleKey, JobLevelKey, StoreKey, ManagerKey,
    CAST(GETDATE() AS DATE), '9999-12-31', 1, HashDiff
FROM chg;
GO