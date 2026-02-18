-- SQL Monitor Runbook
-- Purpose: Real-time SQL monitoring for active and recent executions
-- Usage: Run to monitor currently executing SQL and identify performance issues
-- Target Views: V$SQL_MONITOR, V$SQL_PLAN_MONITOR, GV$SQL_MONITOR
-- Note: Requires Oracle Enterprise Edition with Tuning Pack license

-- Query 1: Currently executing SQL statements being monitored
-- Shows all SQL currently under real-time monitoring
SELECT
    sm.sql_id,
    sm.sql_exec_id,
    sm.sql_exec_start,
    sm.status,
    sm.username,
    sm.module,
    sm.action,
    sm.service_name,
    sm.program,
    ROUND(sm.elapsed_time/1000000, 2) AS elapsed_sec,
    ROUND(sm.cpu_time/1000000, 2) AS cpu_sec,
    sm.buffer_gets,
    sm.disk_reads,
    sm.physical_read_bytes,
    sm.physical_write_bytes,
    sm.fetches,
    sm.sql_text
FROM v$sql_monitor sm
WHERE sm.status = 'EXECUTING'
ORDER BY sm.elapsed_time DESC;

-- Query 2: Long-running monitored SQL (active and recent)
-- SQL executions that have exceeded threshold duration
SELECT
    sm.sql_id,
    sm.sql_exec_id,
    sm.sql_exec_start,
    sm.last_refresh_time,
    sm.status,
    sm.username,
    sm.module,
    ROUND(sm.elapsed_time/1000000, 2) AS elapsed_sec,
    ROUND(sm.cpu_time/1000000, 2) AS cpu_sec,
    ROUND(sm.user_io_wait_time/1000000, 2) AS io_wait_sec,
    ROUND(sm.concurrency_wait_time/1000000, 2) AS concurrency_wait_sec,
    ROUND(sm.application_wait_time/1000000, 2) AS app_wait_sec,
    sm.buffer_gets,
    sm.disk_reads,
    sm.px_servers_requested,
    sm.px_servers_allocated,
    CASE
        WHEN sm.px_servers_allocated < sm.px_servers_requested THEN 'DOWNGRADED'
        WHEN sm.px_servers_requested > 0 THEN 'PARALLEL'
        ELSE 'SERIAL'
    END AS parallel_status,
    SUBSTR(sm.sql_text, 1, 100) AS sql_preview
FROM v$sql_monitor sm
WHERE sm.elapsed_time > 5000000  -- > 5 seconds
ORDER BY sm.elapsed_time DESC
FETCH FIRST 50 ROWS ONLY;

-- Query 3: SQL Monitor plan statistics
-- Detailed execution statistics per plan operation
SELECT
    spm.sql_id,
    spm.sql_exec_id,
    spm.plan_line_id,
    spm.plan_operation,
    spm.plan_options,
    spm.plan_object_owner,
    spm.plan_object_name,
    spm.plan_depth,
    spm.plan_cardinality AS estimated_rows,
    spm.output_rows AS actual_rows,
    CASE
        WHEN spm.plan_cardinality > 0
        THEN ROUND(spm.output_rows / spm.plan_cardinality, 2)
        ELSE NULL
    END AS cardinality_ratio,
    spm.starts,
    ROUND(spm.elapsed_time/1000000, 4) AS elapsed_sec,
    spm.physical_read_requests,
    spm.physical_read_bytes,
    spm.physical_write_requests,
    spm.physical_write_bytes
FROM v$sql_plan_monitor spm
WHERE spm.sql_exec_id = (
    SELECT MAX(sql_exec_id)
    FROM v$sql_monitor
    WHERE status = 'EXECUTING'
      AND elapsed_time = (SELECT MAX(elapsed_time) FROM v$sql_monitor WHERE status = 'EXECUTING')
)
ORDER BY spm.plan_line_id;

-- Query 4: Parallel execution monitoring
-- Real-time view of parallel SQL execution
SELECT
    sm.sql_id,
    sm.sql_exec_id,
    sm.status,
    sm.px_servers_requested,
    sm.px_servers_allocated,
    sm.px_maxdop,
    sm.px_is_cross_instance,
    CASE
        WHEN sm.px_servers_allocated = 0 THEN 'SERIAL'
        WHEN sm.px_servers_allocated < sm.px_servers_requested THEN 'DOWNGRADED'
        ELSE 'FULL PARALLEL'
    END AS px_status,
    sm.px_servers_allocated - sm.px_servers_requested AS px_shortfall,
    ROUND(sm.elapsed_time/1000000, 2) AS elapsed_sec,
    ROUND(sm.cpu_time/1000000, 2) AS cpu_sec,
    sm.buffer_gets,
    sm.disk_reads,
    sm.username,
    SUBSTR(sm.sql_text, 1, 80) AS sql_preview
FROM v$sql_monitor sm
WHERE sm.px_servers_requested > 0
  AND sm.sql_exec_start > SYSDATE - 1/24  -- Last hour
ORDER BY sm.elapsed_time DESC;

-- Query 5: Wait event breakdown for monitored SQL
-- Shows where time is being spent for active SQL
SELECT
    sm.sql_id,
    sm.sql_exec_id,
    sm.status,
    sm.username,
    ROUND(sm.elapsed_time/1000000, 2) AS elapsed_sec,
    ROUND(sm.cpu_time/1000000, 2) AS cpu_sec,
    ROUND(sm.user_io_wait_time/1000000, 2) AS io_wait_sec,
    ROUND(sm.concurrency_wait_time/1000000, 2) AS concurrency_sec,
    ROUND(sm.cluster_wait_time/1000000, 2) AS cluster_wait_sec,
    ROUND(sm.application_wait_time/1000000, 2) AS app_wait_sec,
    ROUND(sm.plsql_exec_time/1000000, 2) AS plsql_sec,
    ROUND(sm.java_exec_time/1000000, 2) AS java_sec,
    -- Breakdown percentages
    ROUND(sm.cpu_time/NULLIF(sm.elapsed_time, 0) * 100, 1) AS cpu_pct,
    ROUND(sm.user_io_wait_time/NULLIF(sm.elapsed_time, 0) * 100, 1) AS io_pct,
    ROUND(sm.concurrency_wait_time/NULLIF(sm.elapsed_time, 0) * 100, 1) AS concurrency_pct
FROM v$sql_monitor sm
WHERE sm.status IN ('EXECUTING', 'DONE')
  AND sm.sql_exec_start > SYSDATE - 1/24
ORDER BY sm.elapsed_time DESC
FETCH FIRST 30 ROWS ONLY;

-- Query 6: Cardinality estimation accuracy
-- Identifies plan operations with poor cardinality estimates
SELECT
    spm.sql_id,
    spm.sql_exec_id,
    spm.plan_line_id,
    spm.plan_operation || ' ' || NVL(spm.plan_options, '') AS operation,
    spm.plan_object_name AS object_name,
    spm.plan_cardinality AS estimated_rows,
    spm.output_rows AS actual_rows,
    CASE
        WHEN spm.plan_cardinality > 0
        THEN ROUND(spm.output_rows / spm.plan_cardinality, 2)
        ELSE NULL
    END AS estimate_ratio,
    CASE
        WHEN spm.output_rows > spm.plan_cardinality * 10 THEN 'SEVERE UNDERESTIMATE'
        WHEN spm.output_rows > spm.plan_cardinality * 2 THEN 'UNDERESTIMATE'
        WHEN spm.output_rows * 10 < spm.plan_cardinality THEN 'SEVERE OVERESTIMATE'
        WHEN spm.output_rows * 2 < spm.plan_cardinality THEN 'OVERESTIMATE'
        ELSE 'ACCURATE'
    END AS estimate_quality
FROM v$sql_plan_monitor spm
WHERE spm.plan_cardinality > 0
  AND spm.output_rows > 0
  AND (spm.output_rows > spm.plan_cardinality * 2
       OR spm.output_rows * 2 < spm.plan_cardinality)
  AND spm.sql_exec_start > SYSDATE - 1/24
ORDER BY ABS(spm.output_rows - spm.plan_cardinality) DESC
FETCH FIRST 50 ROWS ONLY;

-- Query 7: I/O intensive operations in monitored SQL
-- Shows plan operations with high physical reads
SELECT
    spm.sql_id,
    spm.sql_exec_id,
    spm.plan_line_id,
    spm.plan_operation || ' ' || NVL(spm.plan_options, '') AS operation,
    spm.plan_object_owner || '.' || spm.plan_object_name AS object,
    spm.physical_read_requests,
    ROUND(spm.physical_read_bytes/1024/1024, 2) AS physical_read_mb,
    spm.physical_write_requests,
    ROUND(spm.physical_write_bytes/1024/1024, 2) AS physical_write_mb,
    spm.output_rows,
    ROUND(spm.elapsed_time/1000000, 4) AS elapsed_sec
FROM v$sql_plan_monitor spm
WHERE spm.physical_read_bytes > 1024*1024*10  -- > 10 MB
  AND spm.sql_exec_start > SYSDATE - 1/24
ORDER BY spm.physical_read_bytes DESC
FETCH FIRST 30 ROWS ONLY;

-- Query 8: SQL Monitor report generation
-- Generates SQL Monitor report for a specific SQL_ID
-- Note: Use DBMS_SQLTUNE.REPORT_SQL_MONITOR for full reports
SELECT
    sm.sql_id,
    sm.sql_exec_id,
    sm.sql_exec_start,
    sm.status,
    sm.username,
    sm.elapsed_time/1000000 AS elapsed_sec,
    'SELECT DBMS_SQLTUNE.REPORT_SQL_MONITOR(sql_id=>''' || sm.sql_id ||
    ''', sql_exec_id=>' || sm.sql_exec_id ||
    ', type=>''TEXT'') FROM DUAL;' AS report_command
FROM v$sql_monitor sm
WHERE sm.elapsed_time > 5000000
ORDER BY sm.elapsed_time DESC
FETCH FIRST 10 ROWS ONLY;

-- Query 9: Monitored SQL summary by module/program
-- Aggregated view of SQL monitor data by application
SELECT
    sm.module,
    sm.program,
    sm.service_name,
    COUNT(*) AS execution_count,
    COUNT(CASE WHEN sm.status = 'EXECUTING' THEN 1 END) AS currently_running,
    ROUND(SUM(sm.elapsed_time)/1000000, 2) AS total_elapsed_sec,
    ROUND(AVG(sm.elapsed_time)/1000000, 2) AS avg_elapsed_sec,
    ROUND(MAX(sm.elapsed_time)/1000000, 2) AS max_elapsed_sec,
    SUM(sm.buffer_gets) AS total_buffer_gets,
    SUM(sm.disk_reads) AS total_disk_reads
FROM v$sql_monitor sm
WHERE sm.sql_exec_start > SYSDATE - 1  -- Last 24 hours
GROUP BY sm.module, sm.program, sm.service_name
HAVING COUNT(*) > 1
ORDER BY total_elapsed_sec DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 10: Cross-instance parallel execution (RAC)
-- For RAC environments, shows distributed parallel execution
SELECT
    sm.inst_id,
    sm.sql_id,
    sm.sql_exec_id,
    sm.status,
    sm.px_servers_allocated,
    sm.px_is_cross_instance,
    ROUND(sm.elapsed_time/1000000, 2) AS elapsed_sec,
    sm.username,
    sm.module
FROM gv$sql_monitor sm
WHERE sm.px_is_cross_instance = 'Y'
  AND sm.sql_exec_start > SYSDATE - 1/24
ORDER BY sm.elapsed_time DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 11: SQL statements that should be monitored but aren't
-- Identifies long-running SQL not captured by SQL Monitor
-- (SQL Monitor has memory limits and may not capture all SQL)
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.program,
    s.sql_id,
    ROUND((SYSDATE - s.sql_exec_start) * 86400, 2) AS running_seconds,
    s.sql_exec_start,
    'Not in SQL Monitor' AS monitoring_status,
    sq.sql_text
FROM v$session s
LEFT JOIN v$sql sq ON s.sql_id = sq.sql_id AND s.sql_child_number = sq.child_number
WHERE s.status = 'ACTIVE'
  AND s.sql_exec_start IS NOT NULL
  AND (SYSDATE - s.sql_exec_start) * 86400 > 60  -- Running > 60 seconds
  AND NOT EXISTS (
      SELECT 1 FROM v$sql_monitor sm
      WHERE sm.sql_id = s.sql_id
        AND sm.sql_exec_start = s.sql_exec_start
  )
ORDER BY running_seconds DESC;
