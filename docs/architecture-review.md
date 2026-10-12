# Architecture review and delivery plan

Reviewed: 2026-10-12. Baseline: `JobPilot_Architecture.md`. The folder contained that document only: no application, tests, migrations, or Git repository. Findings below are design gaps, not reproduced software defects. No live integrations have been tested.

## Assessment

Keep the modular monolith, PostgreSQL, deterministic matching, explicit submission approval, and manual fallback. They are sensible foundations. The current document is a useful outline, but not an implementation contract. Its full acceptance criteria are much larger than a one-day MVP.

## Findings and required changes

| Priority | Gap in the document | Consequence | Implementation decision |
|---|---|---|---|
| P0 | Approval references a draft but does not define immutability, expiry enforcement, or invalidation. | A reviewed application could be submitted with changed answers or resume. | Freeze draft, resume hash, destination and answers under one approval digest. New edits revoke approval. Validate expiry and atomically consume approval when creating the submission attempt. |
| P0 | Individual foreign keys do not enforce ownership across applications, resumes, drafts and approvals. | Valid IDs could connect records belonging to different users. | Derive user from the authenticated session; enforce compound ownership references and service authorization. Test every cross-user read and mutation. Add user ownership to status suggestions explicitly. |
| P0 | Lease expiry and uncertain external submission are described without a crash-recovery protocol. | A crash after submission but before persistence can cause duplicates. | Persist attempt before external work. Use lease fencing for database completion. Expired non-idempotent attempts enter NEEDS_REVIEW; reconcile evidence before any new attempt. A lease cannot cancel an already-running external request. |
| P1 | State machine is a linear chain rather than a transition table. | Manual imports, direct interviews, rejection before interview, and concurrent updates are undefined. | Define allowed commands per state, including manual APPLIED with evidence, rejection from active states, and withdrawal. Check expected record version and write event plus state in one transaction. |
| P1 | Persisted schedules have no schema; scheduler leadership and task-key uniqueness are undefined. | Restarts or multiple schedulers can lose or duplicate work. | Add schedules with next_run_at, timezone and misfire policy; database leader lock; unique scheduled occurrence key; task heartbeat, lease token, attempt history and dead-letter status. |
| P1 | Eligibility requires experience, work authorization and deadline, but these lack structured schema fields. Boolean eligible cannot represent uncertainty. | Missing data may look like eligibility or rejection. | Use eligible/ineligible/needs_review; typed nullable inputs and source evidence. Treat absent requirements as unknown, never invented restrictions. Store profile, job and scoring version for each result. |
| P1 | Source-ID uniqueness is mistaken for general deduplication. | Cross-source duplicates remain; failed or partial fetches may close live jobs. | Keep source identities authoritative; make cross-source merges conservative and reversible. Close postings only after a complete successful source snapshot and a grace period. Track content revisions. |
| P1 | Gmail has no durable sync cursor, scope contract or recovery design. | Missed messages, repeated suggestions, or an integration that cannot deploy as assumed. | Add per-account cursor/checkpoint and sync runs, bounded initial import, deduplicated proposals and recovery after invalid cursors. Confirm current provider requirements during implementation. Use sender/content evidence; thread ID alone cannot identify an application. |
| P1 | Login exists without account bootstrap, session lifecycle or OAuth callback routes. | Authentication is not implementable from the listed contract alone. | Choose private single-user bootstrap for first release; secure sessions, logout, expiration, CSRF protection where applicable, login throttling and OAuth state validation before external connections. |
| P1 | Resume upload, extraction and fact verification are named but not specified. | Unsafe uploads or fabricated resume claims can pass through undefined checks. | Limit file types and sizes, use private storage and authorized downloads, isolate parsing, and retain immutable originals. Tailored claims must reference approved profile facts; unsupported claims require review. |
| P1 | Untrusted job descriptions and email enter LLM workflows without a trust boundary. | Embedded instructions may influence generation or trigger tools. | Treat retrieved content as data; schema-validate outputs and prohibit generated content from authorizing actions. Keep external side effects behind deterministic checks. |
| P2 | API lists omit pagination, error shape, version conflicts and idempotency semantics. | Clients cannot reliably retry or handle asynchronous failures. | Document cursor pagination, structured errors, optimistic concurrency, and user/route-scoped idempotency keys bound to request hashes. Define task terminal states. |
| P2 | Notifications, deletion, audit retention and key rotation are aspirations without recovery contracts. | Lost notifications or indefinite personal-data retention. | Transactional outbox; idempotent delivery; explicit retention and deletion jobs covering files, messages, derived content and browser sessions. Define backup restore and key rotation procedures. |

P0 items are release blockers for automated submission or multi-user use. They do not prevent a private manual-tracking prototype with those features disabled.

## Same-day scope

Planning estimate, not a completion promise: approximately 6–10 focused implementation hours for a private local vertical slice, assuming Python/Node/PostgreSQL are available and setup works. This is not measured throughput. Unknown environment problems can extend it; it may not fit the remaining hours today.

1. Foundation, migrations, private account/session, profile and health checks: 1–2 hours.
2. Manual job entry, list/detail/save, structured eligibility and deterministic scoring: 1.5–2.5 hours.
3. Manual application tracking, valid transitions and immutable timeline: 1.5–2 hours.
4. Usable React UI, integration tests, browser walkthrough and setup documentation: 2–3.5 hours.

This slice intentionally does not satisfy the original two-source discovery, resume-import, Gmail or submission acceptance criteria. Display unavailable features as unavailable. No demo data should masquerade as live jobs.

After the slice, budget roughly 1–2 additional focused days for two source adapters and durable scheduling; 1–2 for resume versions and reviewed drafts; 1–3 for Gmail sync and status suggestions; 2–5 for a single supported submission adapter and crash/reconciliation testing. These are rough sequential engineering ranges with low confidence until provider access and site behavior are verified. OAuth approval, account access and site restrictions can add elapsed time. A production SaaS release needs separate hardening and operational validation; no fixed completion date is justified yet.

## Evidence required before calling the slice complete

- Fresh PostgreSQL database migrates successfully; restarting the API preserves data.
- Authentication rejects unauthorized access and foreign-user record IDs.
- Positive, negative and missing-information matching fixtures have hand-checkable outcomes.
- Invalid and concurrent status changes fail without corrupting the timeline.
- Browser flow: sign in, edit profile, create and save job, inspect match, track application and view events.
- README commands work from a clean checkout; CI runs the actual checks.

Later milestones additionally require source replay/failure tests, lease and stale-worker tests, approval invalidation tests, Gmail replay tests, and uncertain-submission crash tests. SQLite-only tests are not proof of PostgreSQL worker behavior.

## Repository maintenance

Use this folder as the monorepo. Keep the supplied architecture as the original proposal and record implementation decisions in docs. Commit coherent features with relevant tests; use PRs and CI when a remote is connected. Keep real resumes, mail, tokens, secrets and browser profiles out of Git. Default a new remote to private unless the owner requests public visibility.

Status at the time of the original review: local repository initialized; implementation and remote setup had not started. Subsequent delivery is recorded in [delivery-status.md](delivery-status.md). The user subsequently authorized a public repository and module-by-module pushes.
