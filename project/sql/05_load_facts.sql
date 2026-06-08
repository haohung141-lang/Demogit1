
-- Nạp dữ liệu từ staging sang các bảng Fact trong Data Warehouse.
-- Dữ liệu Fact chứa các chỉ số đo lường phục vụ phân tích như performance, KPI và business outcomes.
-- chạy sau 04_merge_dimensions.sql vì Fact cần tham chiếu khóa từ các bảng Dimension.
-- FactEmployeeMonthlyPerformance
INSERT INTO dwh.FactEmployeeMonthlyPerformance (
    EmployeeKey, DateKey, Performance_Rating, Training_Hours, Overtime_Hours,
    Absenteeism_Days, Promotion_Flag, Salary_Increase_Flag, Monthly_Bonus,
    Benefits_Cost, Employee_Satisfaction, Engagement_Index, Manager_Evaluation
)
SELECT
    de.EmployeeKey,
    dd.DateKey,
    CAST(mp.Performance_Rating AS DECIMAL(10,2)),
    CAST(mp.Training_Hours AS INT),
    CAST(mp.Overtime_Hours AS INT),
    CAST(mp.Absenteeism_Days AS INT),
    CAST(mp.Promotion_Flag AS BIT),
    CAST(mp.Salary_Increase_Flag AS BIT),
    CAST(mp.Monthly_Bonus AS DECIMAL(18,2)),
    CAST(mp.Benefits_Cost AS DECIMAL(18,2)),
    CAST(mp.Employee_Satisfaction AS DECIMAL(10,2)),
    CAST(mp.Engagement_Index AS DECIMAL(10,2)),
    CAST(mp.Manager_Evaluation AS DECIMAL(10,2))
FROM stg.monthly_performance mp
JOIN dwh.DimEmployee de
  ON de.Employee_Id = mp.Employee_Id
 AND de.Is_Current = 1
JOIN dwh.DimDate dd
  ON dd.FullDate = mp.Month_Start_Date
WHERE NOT EXISTS (
    SELECT 1
    FROM dwh.FactEmployeeMonthlyPerformance f
    WHERE f.EmployeeKey = de.EmployeeKey
      AND f.DateKey = dd.DateKey
);
GO

-- FactRoleKpis
INSERT INTO dwh.FactRoleKpis (
    EmployeeKey, DateKey, KpiKey, Kpi_Value, Productivity_Index
)
SELECT
    de.EmployeeKey,
    dd.DateKey,
    dk.KpiKey,
    CAST(rk.Kpi_Value AS DECIMAL(18,4)),
    CAST(rk.Productivity_Index AS DECIMAL(18,4))
FROM stg.role_kpis_long rk
JOIN dwh.DimEmployee de
  ON de.Employee_Id = rk.Employee_Id
 AND de.Is_Current = 1
JOIN dwh.DimDate dd
  ON dd.FullDate = rk.Month_Start_Date
JOIN dwh.DimKpi dk
  ON dk.KpiName = rk.Kpi_Name
WHERE NOT EXISTS (
    SELECT 1
    FROM dwh.FactRoleKpis f
    WHERE f.EmployeeKey = de.EmployeeKey
      AND f.DateKey = dd.DateKey
      AND f.KpiKey = dk.KpiKey
);
GO

-- FactBusinessOutcomes
INSERT INTO dwh.FactBusinessOutcomes (
    StoreKey, DepartmentKey, DateKey, Sales_Target, Sales_Actual,
    Customer_Satisfaction, Nps_Score, Waste_Percentage, On_Time_Delivery
)
SELECT
    ds.StoreKey,
    ddm.DepartmentKey,
    ddt.DateKey,
    CAST(bo.Sales_Target AS DECIMAL(18,2)),
    CAST(bo.Sales_Actual AS DECIMAL(18,2)),
    CAST(bo.Customer_Satisfaction AS DECIMAL(10,2)),
    CAST(bo.Nps_Score AS DECIMAL(10,2)),
    CAST(bo.Waste_Percentage AS DECIMAL(10,4)),
    CAST(bo.On_Time_Delivery AS DECIMAL(10,2))
FROM stg.business_outcomes bo
JOIN dwh.DimStore ds
  ON ds.Store_Id = bo.Store_Id
JOIN dwh.DimDepartment ddm
  ON ddm.DepartmentName = bo.Department
JOIN dwh.DimDate ddt
  ON ddt.FullDate = bo.Month_Start_Date
WHERE NOT EXISTS (
    SELECT 1
    FROM dwh.FactBusinessOutcomes f
    WHERE f.StoreKey = ds.StoreKey
      AND f.DepartmentKey = ddm.DepartmentKey
      AND f.DateKey = ddt.DateKey
);
GO