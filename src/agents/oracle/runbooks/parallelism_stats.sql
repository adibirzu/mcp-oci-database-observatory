-- Parallelism Statistics Runbook
-- Purpose: Monitor parallel execution and detect downgrade issues
-- Usage: Run to analyze parallel query performance and identify bottlenecks
-- Target Views: V$PQ_SESSTAT, V$PX_SESSION, V$PX_PROCESS, V$SQL_PLAN, DBA_HIST_PGA_TARGET_ADVICE

-- Query 1: Current parallel sessions and their slaves
-- Shows active parallel operations with slave allocation
SELECT
    qc.sid AS coordinator_sid,
    qc.serial# AS coordinator_serial,
    s.username,
    s.program,
    qc.inst_id,
    qc.server_set,
    qc.degree,
    qc.req_degree AS requested_degree,
    CASE
        WHEN qc.degree < qc.req_degree THEN 'DOWNGRADED'
        WHEN qc.degree = qc.req_degree THEN 'FULL'
        ELSE 'SERIAL'
    END AS parallel_status,
    COUNT(px.sid) AS active_slaves,
    qc.sql_id
FROM v$px_session qc
LEFT JOIN v$px_process px ON qc.qcsid = px.qcsid
LEFT JOIN v$session s ON qc.sid = s.sid AND qc.serial# = s.serial#
WHERE qc.qcsid IS NOT NULL
GROUP BY qc.sid, qc.serial#, s.username, s.program, qc.inst_id,
         qc.server_set, qc.degree, qc.req_degree, qc.sql_id
ORDER BY qc.degree DESC;

-- Query 2: Parallel execution statistics summary
-- Overall parallel execution health metrics
SELECT
    statistic,
    value,
    CASE statistic
        WHEN 'Queries Parallelized' THEN 'Total queries executed in parallel'
        WHEN 'DML Parallelized' THEN 'Total DML ops executed in parallel'
        WHEN 'DDL Parallelized' THEN 'Total DDL ops executed in parallel'
        WHEN 'DFO Trees' THEN 'Data Flow Operation trees created'
        WHEN 'Server Threads' THEN 'PX server processes used'
        WHEN 'Allocation Height' THEN 'Max parallel degree allocated'
        WHEN 'Allocation Width' THEN 'Max server sets allocated'
        WHEN 'Local Msgs Sent' THEN 'Messages between local slaves'
        WHEN 'Distr Msgs Sent' THEN 'Messages between distributed slaves'
        WHEN 'Local Msgs Recv''d' THEN 'Messages received locally'
        WHEN 'Distr Msgs Recv''d' THEN 'Messages received distributed'
        ELSE 'Other statistic'
    END AS description
FROM v$pq_sysstat
WHERE value > 0
ORDER BY value DESC;

-- Query 3: Parallel downgrade reasons
-- Identifies why parallel operations were downgraded
SELECT
    px.sql_id,
    sq.sql_text,
    px.degree AS actual_degree,
    px.req_degree AS requested_degree,
    px.req_degree - px.degree AS degree_reduction,
    CASE
        WHEN px.degree = 1 THEN 'Serialized (No Parallelism)'
        WHEN px.degree < px.req_degree THEN 'Reduced Parallelism'
        ELSE 'Full Parallelism'
    END AS execution_mode,
    s.username,
    s.program
FROM v$px_session px
JOIN v$session s ON px.sid = s.sid AND px.serial# = s.serial#
LEFT JOIN v$sql sq ON px.sql_id = sq.sql_id AND ROWNUM = 1
WHERE px.degree < px.req_degree
ORDER BY degree_reduction DESC;

-- Query 4: Parallel server pool usage
-- Shows availability and usage of parallel server processes
SELECT
    server_name,
    status,
    pid,
    spid,
    sid,
    serial#,
    CASE status
        WHEN 'BUSY' THEN 'Currently executing parallel operation'
        WHEN 'IDLE' THEN 'Available for parallel operations'
        WHEN 'HOLD' THEN 'Temporarily held for reuse'
        ELSE status
    END AS status_description
FROM v$px_process
ORDER BY status, server_name;

-- Query 5: Parallel hint effectiveness in recent SQL
-- Shows if hints are being honored or overridden
SELECT
    sql_id,
    plan_hash_value,
    operation,
    options,
    other_tag,
    distribution,
    pq_distribution,
    CASE
        WHEN other_tag LIKE '%PARALLEL%' THEN 'Parallel Execution'
        WHEN other_tag LIKE '%SERIAL%' THEN 'Serial Execution'
        ELSE NVL(other_tag, 'Standard')
    END AS execution_type,
    cost,
    cardinality,
    bytes,
    cpu_cost,
    io_cost
FROM v$sql_plan
WHERE other_tag IS NOT NULL
  OR operation LIKE '%PX%'
  OR options LIKE '%PARALLEL%'
ORDER BY cost DESC NULLS LAST
FETCH FIRST 30 ROWS ONLY;

-- Query 6: Resource Manager parallel degree limits
-- Check if Resource Manager is limiting parallel degree
SELECT
    consumer_group,
    active_sessions,
    execution_waiters,
    current_pq_servers_used,
    parallel_server_limit,
    CASE
        WHEN current_pq_servers_used >= parallel_server_limit THEN 'AT LIMIT'
        WHEN parallel_server_limit = 0 THEN 'UNLIMITED'
        ELSE 'AVAILABLE'
    END AS pq_status,
    ROUND(current_pq_servers_used / NULLIF(parallel_server_limit, 0) * 100, 2) AS pq_pct_used
FROM v$rsrc_consumer_group
WHERE current_pq_servers_used > 0
   OR parallel_server_limit > 0
ORDER BY current_pq_servers_used DESC;

-- Query 7: Parallel parameter settings
-- Shows key parameters affecting parallel execution
SELECT
    name,
    value,
    description
FROM v$parameter
WHERE name IN (
    'parallel_max_servers',
    'parallel_min_servers',
    'parallel_servers_target',
    'parallel_adaptive_multi_user',
    'parallel_degree_policy',
    'parallel_degree_limit',
    'parallel_force_local',
    'parallel_min_time_threshold',
    'parallel_threads_per_cpu',
    'cpu_count',
    'pga_aggregate_target',
    'pga_aggregate_limit'
)
ORDER BY name;

-- Query 8: PGA memory pressure affecting parallelism
-- High PGA usage can cause parallel downgrade
SELECT
    'PGA Usage' AS metric,
    ROUND(pga_target_for_estimate/1024/1024, 2) AS pga_target_mb,
    pga_target_factor AS factor,
    estd_extra_bytes_rw/1024/1024 AS estd_extra_mb_to_disk,
    estd_overalloc_count,
    CASE
        WHEN estd_overalloc_count > 0 THEN 'MEMORY PRESSURE - May cause parallel downgrade'
        WHEN pga_target_factor < 1 THEN 'BELOW TARGET'
        ELSE 'OK'
    END AS status
FROM v$pga_target_advice
WHERE pga_target_factor BETWEEN 0.5 AND 2
ORDER BY pga_target_factor;

-- Query 9: Parallel query waits
-- Shows waits related to parallel execution
SELECT
    event,
    wait_class,
    total_waits,
    total_timeouts,
    time_waited,
    average_wait,
    ROUND(time_waited / NULLIF(total_waits, 0), 2) AS avg_wait_ms
FROM v$system_event
WHERE event LIKE '%PX%'
   OR event LIKE '%parallel%'
   OR event LIKE '%Parallel%'
ORDER BY time_waited DESC;

-- Query 10: SQL statements experiencing parallel downgrade (from AWR)
-- Historical analysis of parallel downgrades
SELECT
    ss.sql_id,
    ss.plan_hash_value,
    st.sql_text,
    ss.px_servers_execs_total AS total_px_executions,
    ss.px_servers_execs_delta AS recent_px_executions,
    ROUND(ss.elapsed_time_delta/1000000, 2) AS elapsed_sec,
    ROUND(ss.cpu_time_delta/1000000, 2) AS cpu_sec,
    ss.executions_delta AS executions
FROM dba_hist_sqlstat ss
JOIN dba_hist_sqltext st ON ss.sql_id = st.sql_id
WHERE ss.px_servers_execs_delta > 0
  AND ss.snap_id > (SELECT MAX(snap_id) - 24 FROM dba_hist_snapshot)
ORDER BY ss.elapsed_time_delta DESC
FETCH FIRST 20 ROWS ONLY;
