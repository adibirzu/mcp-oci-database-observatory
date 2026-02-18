-- Full Table Scans Detection Runbook
-- Purpose: Identify expensive full table scans that may need optimization
-- Usage: Run to find SQL statements causing excessive I/O via full scans
-- Target Views: V$SQL_PLAN, V$SQLAREA, DBA_HIST_SQLSTAT, V$SESSION_LONGOPS

-- Query 1: Active full table scans in progress
-- Real-time detection of ongoing full table scans
SELECT
    sl.sid,
    sl.serial#,
    s.username,
    s.program,
    sl.target AS table_name,
    sl.sofar AS blocks_read,
    sl.totalwork AS total_blocks,
    ROUND(sl.sofar / NULLIF(sl.totalwork, 0) * 100, 2) AS pct_complete,
    sl.elapsed_seconds,
    sl.time_remaining AS est_remaining_sec,
    sl.sql_id,
    t.num_rows AS table_rows,
    ROUND(t.blocks * 8 / 1024, 2) AS table_size_mb
FROM v$session_longops sl
JOIN v$session s ON sl.sid = s.sid AND sl.serial# = s.serial#
LEFT JOIN dba_tables t ON sl.target = t.owner || '.' || t.table_name
WHERE sl.opname = 'Table Scan'
  AND (sl.sofar < sl.totalwork OR sl.time_remaining > 0)
ORDER BY sl.elapsed_seconds DESC;

-- Query 2: SQL statements with full table scans (current cursor cache)
-- Shows active SQL with TABLE ACCESS FULL operations
SELECT
    sp.sql_id,
    sp.child_number,
    sp.object_owner,
    sp.object_name AS table_name,
    sa.executions,
    ROUND(sa.elapsed_time/1000000, 2) AS total_elapsed_sec,
    ROUND(sa.elapsed_time/NULLIF(sa.executions, 0)/1000000, 4) AS avg_elapsed_sec,
    sa.disk_reads,
    ROUND(sa.disk_reads/NULLIF(sa.executions, 0), 2) AS disk_reads_per_exec,
    sa.buffer_gets,
    ROUND(sa.buffer_gets/NULLIF(sa.executions, 0), 2) AS buffer_gets_per_exec,
    sa.rows_processed,
    SUBSTR(sa.sql_text, 1, 200) AS sql_text_preview
FROM v$sql_plan sp
JOIN v$sqlarea sa ON sp.sql_id = sa.sql_id
WHERE sp.operation = 'TABLE ACCESS'
  AND sp.options = 'FULL'
  AND sa.executions > 0
  AND sp.object_name NOT IN (SELECT table_name FROM dba_tables WHERE temporary = 'Y')
ORDER BY sa.elapsed_time DESC
FETCH FIRST 30 ROWS ONLY;

-- Query 3: Large tables being full scanned
-- Focus on large tables where full scans are most expensive
SELECT
    sp.object_owner,
    sp.object_name AS table_name,
    t.num_rows,
    t.blocks AS table_blocks,
    ROUND(t.blocks * 8 / 1024, 2) AS table_size_mb,
    COUNT(DISTINCT sp.sql_id) AS distinct_sql_count,
    SUM(sa.executions) AS total_executions,
    ROUND(SUM(sa.elapsed_time)/1000000, 2) AS total_elapsed_sec,
    ROUND(SUM(sa.disk_reads), 0) AS total_disk_reads,
    ROUND(SUM(sa.buffer_gets), 0) AS total_buffer_gets
FROM v$sql_plan sp
JOIN v$sqlarea sa ON sp.sql_id = sa.sql_id
LEFT JOIN dba_tables t ON sp.object_owner = t.owner AND sp.object_name = t.table_name
WHERE sp.operation = 'TABLE ACCESS'
  AND sp.options = 'FULL'
  AND sa.executions > 0
  AND t.blocks > 1000  -- Tables larger than ~8MB
GROUP BY sp.object_owner, sp.object_name, t.num_rows, t.blocks
ORDER BY total_elapsed_sec DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 4: Full table scans vs Index usage comparison
-- Shows tables being both index scanned and full scanned
SELECT
    t.owner,
    t.table_name,
    t.num_rows,
    ROUND(t.blocks * 8 / 1024, 2) AS table_size_mb,
    (SELECT COUNT(DISTINCT sp.sql_id)
     FROM v$sql_plan sp
     WHERE sp.object_owner = t.owner
       AND sp.object_name = t.table_name
       AND sp.operation = 'TABLE ACCESS'
       AND sp.options = 'FULL') AS full_scan_sql_count,
    (SELECT COUNT(DISTINCT sp.sql_id)
     FROM v$sql_plan sp
     WHERE sp.object_owner = t.owner
       AND sp.object_name = t.table_name
       AND sp.operation LIKE '%INDEX%') AS index_scan_sql_count,
    (SELECT COUNT(*)
     FROM dba_indexes i
     WHERE i.table_owner = t.owner
       AND i.table_name = t.table_name) AS index_count
FROM dba_tables t
WHERE t.owner NOT IN ('SYS', 'SYSTEM', 'DBSNMP', 'OUTLN')
  AND t.temporary = 'N'
  AND t.blocks > 100
  AND EXISTS (
      SELECT 1 FROM v$sql_plan sp
      WHERE sp.object_owner = t.owner
        AND sp.object_name = t.table_name
        AND sp.operation = 'TABLE ACCESS'
        AND sp.options = 'FULL'
  )
ORDER BY t.blocks DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 5: Missing indexes recommendation for full scan tables
-- Identifies tables with full scans that might benefit from indexes
SELECT
    sp.object_owner,
    sp.object_name AS table_name,
    t.num_rows,
    ROUND(t.blocks * 8 / 1024, 2) AS table_size_mb,
    'Consider adding index' AS recommendation,
    sp.sql_id,
    sp.filter_predicates,
    sp.access_predicates
FROM v$sql_plan sp
JOIN dba_tables t ON sp.object_owner = t.owner AND sp.object_name = t.table_name
WHERE sp.operation = 'TABLE ACCESS'
  AND sp.options = 'FULL'
  AND (sp.filter_predicates IS NOT NULL OR sp.access_predicates IS NOT NULL)
  AND t.blocks > 1000
  AND NOT EXISTS (
      SELECT 1 FROM dba_indexes i
      WHERE i.table_owner = sp.object_owner
        AND i.table_name = sp.object_name
  )
ORDER BY t.blocks DESC;

-- Query 6: Full table scan I/O impact (from AWR)
-- Historical analysis of full scan impact on system I/O
SELECT
    snap.begin_interval_time,
    stat.sql_id,
    txt.sql_text,
    stat.executions_delta AS executions,
    ROUND(stat.elapsed_time_delta/1000000, 2) AS elapsed_sec,
    ROUND(stat.disk_reads_delta) AS disk_reads,
    ROUND(stat.buffer_gets_delta) AS buffer_gets,
    ROUND(stat.physical_read_bytes_delta/1024/1024, 2) AS physical_read_mb
FROM dba_hist_sqlstat stat
JOIN dba_hist_snapshot snap ON stat.snap_id = snap.snap_id
    AND stat.instance_number = snap.instance_number
JOIN dba_hist_sqltext txt ON stat.sql_id = txt.sql_id
WHERE EXISTS (
    SELECT 1 FROM dba_hist_sql_plan hp
    WHERE hp.sql_id = stat.sql_id
      AND hp.operation = 'TABLE ACCESS'
      AND hp.options = 'FULL'
)
AND stat.disk_reads_delta > 10000  -- Significant I/O
AND snap.begin_interval_time > SYSDATE - 1
ORDER BY stat.disk_reads_delta DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 7: Tables with stale statistics (may cause optimizer to choose full scan)
-- Stale stats can lead optimizer to incorrect full scan decisions
SELECT
    t.owner,
    t.table_name,
    t.num_rows,
    t.blocks,
    ROUND(t.blocks * 8 / 1024, 2) AS size_mb,
    t.last_analyzed,
    ROUND(SYSDATE - t.last_analyzed) AS days_since_analyzed,
    t.stale_stats,
    'Stats may cause suboptimal full scans' AS warning
FROM dba_tab_statistics t
WHERE t.owner NOT IN ('SYS', 'SYSTEM', 'DBSNMP', 'OUTLN')
  AND (t.stale_stats = 'YES' OR t.last_analyzed < SYSDATE - 30)
  AND t.num_rows > 10000
  AND EXISTS (
      SELECT 1 FROM v$sql_plan sp
      WHERE sp.object_owner = t.owner
        AND sp.object_name = t.table_name
        AND sp.operation = 'TABLE ACCESS'
        AND sp.options = 'FULL'
  )
ORDER BY t.blocks DESC;

-- Query 8: Direct path read operations (parallel full scans)
-- Tracks direct path reads which indicate parallel full table scans
SELECT
    event,
    wait_class,
    total_waits,
    total_timeouts,
    ROUND(time_waited_micro/1000000, 2) AS time_waited_sec,
    ROUND(average_wait/1000, 2) AS avg_wait_ms
FROM v$system_event
WHERE event IN (
    'direct path read',
    'direct path read temp',
    'cell single block physical read',
    'cell multiblock physical read',
    'db file scattered read',
    'db file sequential read'
)
ORDER BY time_waited_micro DESC;

-- Query 9: Optimizer hints being ignored for index usage
-- Shows SQL where index hints might be beneficial
SELECT
    sql_id,
    plan_hash_value,
    operation,
    options,
    object_owner,
    object_name,
    cardinality,
    cost,
    bytes,
    other_xml
FROM v$sql_plan
WHERE operation = 'TABLE ACCESS'
  AND options = 'FULL'
  AND cardinality > 10000  -- Large result sets
  AND cost > 1000          -- High cost operations
ORDER BY cost DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 10: Summary of full table scan impact by schema
-- Aggregated view of full scan impact per schema
SELECT
    sp.object_owner AS schema_name,
    COUNT(DISTINCT sp.object_name) AS tables_with_full_scan,
    COUNT(DISTINCT sp.sql_id) AS distinct_sql_statements,
    SUM(sa.executions) AS total_executions,
    ROUND(SUM(sa.elapsed_time)/1000000, 2) AS total_elapsed_sec,
    ROUND(SUM(sa.disk_reads)) AS total_disk_reads,
    ROUND(SUM(sa.buffer_gets)) AS total_buffer_gets
FROM v$sql_plan sp
JOIN v$sqlarea sa ON sp.sql_id = sa.sql_id
WHERE sp.operation = 'TABLE ACCESS'
  AND sp.options = 'FULL'
  AND sp.object_owner NOT IN ('SYS', 'SYSTEM', 'DBSNMP', 'OUTLN')
  AND sa.executions > 0
GROUP BY sp.object_owner
ORDER BY total_elapsed_sec DESC;
