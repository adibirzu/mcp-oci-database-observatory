-- Blocking Sessions Detection Runbook
-- Purpose: Identify blocking sessions causing lock contention
-- Usage: Run when users report slow queries or lock waits
-- Target Views: V$SESSION, V$LOCK, DBA_BLOCKERS, DBA_WAITERS

-- Query 1: Active blocking tree (hierarchical view of blockers and waiters)
-- Shows the full chain of blocking from root blocker to all waiters
SELECT
    LPAD(' ', 2 * (LEVEL - 1)) || s.sid AS sid_tree,
    s.serial#,
    s.username,
    s.program,
    s.machine,
    s.status,
    s.event,
    s.seconds_in_wait,
    s.sql_id,
    CASE WHEN s.blocking_session IS NOT NULL
         THEN 'WAITING on SID ' || s.blocking_session
         ELSE 'BLOCKER'
    END AS blocking_status,
    o.object_name AS locked_object
FROM v$session s
LEFT JOIN v$locked_object lo ON s.sid = lo.session_id
LEFT JOIN dba_objects o ON lo.object_id = o.object_id
WHERE s.blocking_session IS NOT NULL
   OR s.sid IN (SELECT blocking_session FROM v$session WHERE blocking_session IS NOT NULL)
START WITH s.blocking_session IS NULL
        AND s.sid IN (SELECT blocking_session FROM v$session WHERE blocking_session IS NOT NULL)
CONNECT BY PRIOR s.sid = s.blocking_session
ORDER SIBLINGS BY s.seconds_in_wait DESC;

-- Query 2: Lock contention summary with wait times
-- Shows aggregated view of lock waits by object and lock mode
SELECT
    o.owner,
    o.object_name,
    o.object_type,
    l.locked_mode,
    DECODE(l.locked_mode,
        0, 'None',
        1, 'Null',
        2, 'Row-S (SS)',
        3, 'Row-X (SX)',
        4, 'Share',
        5, 'S/Row-X (SSX)',
        6, 'Exclusive') AS lock_mode_desc,
    COUNT(*) AS session_count,
    SUM(s.seconds_in_wait) AS total_wait_seconds
FROM v$locked_object l
JOIN dba_objects o ON l.object_id = o.object_id
JOIN v$session s ON l.session_id = s.sid
GROUP BY o.owner, o.object_name, o.object_type, l.locked_mode
ORDER BY total_wait_seconds DESC
FETCH FIRST 20 ROWS ONLY;

-- Query 3: Detailed blocker information with SQL text
-- Shows what the blocking session is actually doing
SELECT
    b.holding_session AS blocker_sid,
    sb.serial# AS blocker_serial,
    sb.username AS blocker_user,
    sb.program AS blocker_program,
    sb.machine AS blocker_machine,
    sb.sql_id AS blocker_sql_id,
    (SELECT sql_text FROM v$sql WHERE sql_id = sb.sql_id AND ROWNUM = 1) AS blocker_sql,
    sb.status AS blocker_status,
    sb.logon_time AS blocker_logon,
    b.waiting_session AS waiter_sid,
    sw.username AS waiter_user,
    sw.event AS waiter_event,
    sw.seconds_in_wait AS wait_seconds
FROM dba_blockers b
JOIN dba_waiters w ON b.holding_session = w.holding_session
JOIN v$session sb ON b.holding_session = sb.sid
JOIN v$session sw ON b.waiting_session = sw.sid
ORDER BY sw.seconds_in_wait DESC;

-- Query 4: Enqueue (lock) waits by type
-- Shows which lock types are causing the most contention
SELECT
    eq_type,
    DECODE(eq_type,
        'TX', 'Transaction (Row Lock)',
        'TM', 'DML (Table Lock)',
        'UL', 'User Lock',
        'CF', 'Control File',
        'CI', 'Cross-Instance',
        'DF', 'Data File',
        'DL', 'Direct Loader',
        'DM', 'Database Mount',
        'DR', 'Distributed Recovery',
        'FS', 'File Set',
        'HW', 'Segment High Water Mark',
        'IN', 'Instance Number',
        'IR', 'Instance Recovery',
        'IS', 'Instance State',
        'IV', 'Library Cache Invalidation',
        'JQ', 'Job Queue',
        'KK', 'Thread Kick',
        'LA', 'Library Cache Lock',
        'LB', 'Library Cache Lock',
        'LC', 'Library Cache Lock',
        'MM', 'Mount Definition',
        'MR', 'Media Recovery',
        'PF', 'Password File',
        'PI', 'Parallel Slaves',
        'PR', 'Process Startup',
        'PS', 'Parallel Slave Sync',
        'RT', 'Redo Thread',
        'SC', 'System Commit Number',
        'SM', 'SMON',
        'SN', 'Sequence Number',
        'SQ', 'Sequence Cache',
        'SS', 'Sort Segment',
        'ST', 'Space Transaction',
        'SV', 'Sequence Value',
        'TA', 'Transaction Autonomous',
        'TS', 'Temporary Segment',
        'TT', 'Temporary Table',
        'UN', 'User Name',
        'WL', 'Write Redo Log',
        eq_type) AS lock_type_desc,
    total_req# AS total_requests,
    total_wait# AS total_waits,
    succ_req# AS successful_requests,
    failed_req# AS failed_requests,
    cum_wait_time AS cumulative_wait_ms
FROM v$enqueue_stat
WHERE total_wait# > 0
ORDER BY cum_wait_time DESC
FETCH FIRST 15 ROWS ONLY;

-- Query 5: Sessions waiting for locks right now
-- Real-time view of sessions in lock wait
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.program,
    s.event,
    s.p1text || ': ' || s.p1 AS param1,
    s.p2text || ': ' || s.p2 AS param2,
    s.p3text || ': ' || s.p3 AS param3,
    s.seconds_in_wait,
    s.blocking_session,
    s.blocking_session_status,
    s.sql_id,
    s.prev_sql_id
FROM v$session s
WHERE s.state = 'WAITING'
  AND s.event LIKE '%enq%'
ORDER BY s.seconds_in_wait DESC;
