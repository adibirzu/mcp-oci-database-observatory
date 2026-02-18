-- Long Running Operations Runbook
-- Purpose: Monitor and analyze long-running database operations
-- Usage: Run to identify operations exceeding expected duration
-- Target Views: V$SESSION_LONGOPS, V$SESSION, V$SQL

-- Query 1: Currently running long operations with progress
-- Shows active operations with estimated completion time
SELECT
    sl.sid,
    sl.serial#,
    s.username,
    s.program,
    sl.opname AS operation_name,
    sl.target AS target_object,
    sl.target_desc,
    sl.sofar AS work_done,
    sl.totalwork AS total_work,
    CASE
        WHEN sl.totalwork > 0
        THEN ROUND(sl.sofar / sl.totalwork * 100, 2)
        ELSE 0
    END AS pct_complete,
    sl.units,
    sl.elapsed_seconds,
    sl.time_remaining AS est_seconds_remaining,
    TO_CHAR(sl.start_time, 'YYYY-MM-DD HH24:MI:SS') AS start_time,
    CASE
        WHEN sl.time_remaining > 0
        THEN TO_CHAR(SYSDATE + sl.time_remaining/86400, 'YYYY-MM-DD HH24:MI:SS')
        ELSE 'Unknown'
    END AS est_completion,
    sl.sql_id,
    sl.message
FROM v$session_longops sl
JOIN v$session s ON sl.sid = s.sid AND sl.serial# = s.serial#
WHERE sl.sofar < sl.totalwork
   OR sl.time_remaining > 0
ORDER BY sl.elapsed_seconds DESC;

-- Query 2: Historical long operations (last 24 hours)
-- Analysis of completed long operations for pattern detection
SELECT
    sl.opname AS operation_name,
    COUNT(*) AS occurrence_count,
    MIN(sl.elapsed_seconds) AS min_duration_sec,
    AVG(sl.elapsed_seconds) AS avg_duration_sec,
    MAX(sl.elapsed_seconds) AS max_duration_sec,
    SUM(sl.elapsed_seconds) AS total_duration_sec,
    MIN(sl.start_time) AS first_occurrence,
    MAX(sl.start_time) AS last_occurrence
FROM v$session_longops sl
WHERE sl.start_time > SYSDATE - 1
  AND sl.sofar = sl.totalwork  -- Completed operations
GROUP BY sl.opname
HAVING AVG(sl.elapsed_seconds) > 60  -- Operations averaging > 1 minute
ORDER BY total_duration_sec DESC;

-- Query 3: Long operations by object/target
-- Shows which objects are involved in long-running operations
SELECT
    sl.target AS target_object,
    sl.target_desc,
    sl.opname AS operation_type,
    COUNT(*) AS operation_count,
    ROUND(AVG(sl.elapsed_seconds), 2) AS avg_duration_sec,
    MAX(sl.elapsed_seconds) AS max_duration_sec,
    SUM(sl.totalwork) AS total_work_units,
    sl.units
FROM v$session_longops sl
WHERE sl.start_time > SYSDATE - 1
GROUP BY sl.target, sl.target_desc, sl.opname, sl.units
ORDER BY SUM(sl.elapsed_seconds) DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 4: Active sessions with long-running SQL
-- Sessions that have been running SQL for extended periods
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.program,
    s.machine,
    s.status,
    s.sql_id,
    ROUND((SYSDATE - s.sql_exec_start) * 86400, 2) AS sql_elapsed_seconds,
    s.sql_exec_start,
    sq.sql_text,
    sq.elapsed_time/1000000 AS total_elapsed_sec,
    sq.executions,
    CASE
        WHEN sq.executions > 0
        THEN ROUND(sq.elapsed_time/sq.executions/1000000, 2)
        ELSE 0
    END AS avg_elapsed_per_exec_sec
FROM v$session s
LEFT JOIN v$sql sq ON s.sql_id = sq.sql_id AND s.sql_child_number = sq.child_number
WHERE s.status = 'ACTIVE'
  AND s.sql_exec_start IS NOT NULL
  AND (SYSDATE - s.sql_exec_start) * 86400 > 60  -- Running for > 1 minute
ORDER BY sql_elapsed_seconds DESC;

-- Query 5: Full table scans in progress (part of long ops)
-- Detects ongoing table scans which are often long-running
SELECT
    sl.sid,
    sl.serial#,
    s.username,
    sl.opname,
    sl.target AS table_name,
    sl.sofar AS blocks_scanned,
    sl.totalwork AS total_blocks,
    ROUND(sl.sofar / NULLIF(sl.totalwork, 0) * 100, 2) AS pct_complete,
    sl.elapsed_seconds,
    sl.time_remaining,
    sl.sql_id
FROM v$session_longops sl
JOIN v$session s ON sl.sid = s.sid AND sl.serial# = s.serial#
WHERE sl.opname LIKE '%Scan%'
  AND (sl.sofar < sl.totalwork OR sl.time_remaining > 0)
ORDER BY sl.elapsed_seconds DESC;

-- Query 6: Operations exceeding threshold (configurable)
-- Long operations that exceed a specified duration threshold
-- Default threshold: 300 seconds (5 minutes)
SELECT
    sl.sid,
    sl.serial#,
    sl.opname,
    sl.target,
    sl.sofar,
    sl.totalwork,
    sl.units,
    sl.elapsed_seconds,
    sl.time_remaining,
    sl.start_time,
    sl.sql_id,
    sl.message,
    'ALERT: Operation exceeds threshold' AS alert_status
FROM v$session_longops sl
WHERE sl.elapsed_seconds > 300  -- Threshold in seconds
  AND (sl.sofar < sl.totalwork OR sl.time_remaining > 0)
ORDER BY sl.elapsed_seconds DESC;

-- Query 7: Index rebuild/create operations in progress
-- Specifically tracks index maintenance operations
SELECT
    sl.sid,
    sl.serial#,
    s.username,
    sl.opname,
    sl.target AS index_name,
    sl.sofar,
    sl.totalwork,
    ROUND(sl.sofar / NULLIF(sl.totalwork, 0) * 100, 2) AS pct_complete,
    sl.elapsed_seconds,
    sl.time_remaining,
    sl.message
FROM v$session_longops sl
JOIN v$session s ON sl.sid = s.sid AND sl.serial# = s.serial#
WHERE sl.opname IN ('Create Index', 'Index Rebuild', 'Sort/Merge', 'Index Build')
  AND (sl.sofar < sl.totalwork OR sl.time_remaining > 0)
ORDER BY sl.elapsed_seconds DESC;
