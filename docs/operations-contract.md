# Durable background work

Only registered task types may be enqueued. The initial registered type is read-only ATS discovery. There is no generic task-creation HTTP endpoint and this worker must not be reused for external application submission without a separate non-idempotent recovery design.

- PostgreSQL stores tasks, attempts and UTC interval schedules. A short `FOR UPDATE SKIP LOCKED` transaction claims work; network preparation happens after commit.
- A fresh UUID lease token fences each attempt. Heartbeats run every 10 seconds and leases last 45 seconds. Both heartbeat and completion reject an expired or replaced lease. Prepared results and task completion commit in one transaction.
- At most one queued/running task exists per user/resource. Exact idempotency-key replay returns the original task; key reuse with different input is rejected. An active resource task coalesces additional requests.
- Expired safe tasks back off and can retry, up to three attempts. Unknown/non-retry-safe expired tasks require review. Failed attempts retain error codes and timestamps. Internal exception strings are not returned to users.
- Retry delay uses exponential backoff with jitter; provider Retry-After can delay it further (bounded at one day). Permanent feed errors do not retry automatically.
- Each scheduler tick takes a PostgreSQL transaction advisory lock. Due occurrences and next-run updates commit together. Missed intervals coalesce to one run, rather than replaying a backlog. Disabling a schedule stops future ticks; already claimed work may finish.

This uses a small polling scheduler instead of APScheduler for fixed UTC intervals. The database is the scheduling source of truth. It is intentionally not a cron/timezone calendar engine. Independent scheduler/worker processes are connected by the discovery module's CLI.

The queue is at-least-once execution with fenced database effects, not exactly-once external delivery. The runtime has no production throughput claim. The database clock decides leases and due times, reducing host-clock drift issues.
