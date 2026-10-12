# Manual application tracking

This release records what the user did elsewhere. It never submits applications. SAVED/DRAFT/READY_FOR_REVIEW are tracking markers, not generated drafts or submission approvals. APPROVED and SUBMITTING are intentionally unavailable until approved submission exists.

Creation is idempotent per user and job. Status commands require an expected version, a fresh UUID command ID and a note. APPLIED, REJECTED and WITHDRAWN additionally require explicit confirmation. Repeating the identical command ID and payload creates no additional event; reusing the ID for different input returns 409. A replay returns the current application view, which can be newer than the original command.

An application row lock serializes status commands; stale versions return 409. Every successful state change and its event commit together. Event update/delete is blocked by a PostgreSQL trigger. Database administrators can still alter schema or truncate tables; this is operational history, not tamper-proof storage.

Transitions are defined in `backend/app/applications.py`. Direct manual SAVED → APPLIED is supported. Interviews may bypass assessments, offers may bypass interviews, and active applications can be rejected or withdrawn. REJECTED/WITHDRAWN/EXPIRED are terminal in this version. NEEDS_REVIEW can be resolved by a user with a recorded note. applied_at is the time the application was first marked applied here, not a user-supplied historical submission timestamp.

The first slice does not include editing job records, deleting accounts, importing historical timestamps, generated resumes, email evidence, or automated applications. Those require additional contracts and tests before being enabled.
