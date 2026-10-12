# Company discovery and alerts

Implemented 2026-10-12. Discovery reads public company boards through the documented [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) and [Lever Postings API](https://github.com/lever/postings-api). It never submits applications. Greenhouse, Lever global and Lever EU use fixed provider hosts and validated board slugs; arbitrary fetch URLs and redirects are rejected.

## Sources and execution

The suggested list contains Toast, FourKites, Zscaler, Rubrik, Databricks, MongoDB, Cloudflare, Stripe, Palantir and Spotify. This is verified supported-board coverage, not a ranking or comprehensive MNC coverage. Other companies using supported boards can be added manually. Subscriptions belong to the signed-in user, with a maximum of 20. Adding presets is idempotent.

The PostgreSQL scheduler and worker run independently of the API. Default checks are every 15 minutes; manual checks have a five-minute cooldown. Pausing prevents future scheduling; an in-flight check may finish. Missed intervals coalesce. Durable leases, bounded retries and atomic completion follow the [operations contract](operations-contract.md). Queued work requires a running worker; starting the frontend alone does not activate monitoring.

Each complete fetch is bounded to 5,000 records, 32 MiB of decoded response content, 25 Lever pages and a 90-second elapsed check with HTTP timeouts. Incomplete, malformed, oversized or failed responses do not apply partial snapshots or mark jobs closed. Provider throttling respects bounded Retry-After. Large boards beyond these limits require a future partitioning strategy.

## Personal shortlist

The current fixed policy is `chennai-remote-bengaluru8-v1`:

- Software-development and data-analysis title signals; senior/leadership titles are excluded.
- Fresher, graduate, entry-level or 2027 text signals are hints requiring verification against the original posting. Missing signals stay in review.
- Chennai on-site and India-compatible remote can be potential matches. Chennai hybrid or unclear remote restrictions stay in review; known foreign-only remote roles are excluded.
- Bengaluru requires explicit structured INR annual minimum compensation of at least 800,000. Missing, non-INR, straddling or unclear salary stays in review. Explicit maximum below the threshold is excluded. Company reputation never supplies inferred pay.

This policy is separate from profile-based eligibility/matching and is not a guarantee of fresher or batch eligibility. ATS requirements remain unreviewed; skills and salary are not invented. Review the linked employer page before acting.

## Snapshots and notifications

Provider identity is unique within a subscribed source. Content revisions retain original first-seen time; detection time is not employer publication time. Missing jobs close only after at least 24 hours missing and a subsequent complete successful check. Reappearing jobs reopen. This grace period tolerates temporary feed omissions but delays closure detection.

The first successful fetch is a baseline with no alert flood. Later new identities classified as potential matches or needing review create a persisted summary notice, atomically with the task result. Updates and reappearances do not count as new identities. Cross-provider duplicates are not globally deduplicated. An open signed-in app polls unread notices every 15 seconds; dismissal persists. There is no OS notification, closed-browser push or instant posting-time guarantee.

Import saves a private immutable opportunity snapshot with source provenance. Later feed changes never overwrite that saved job or its application history; repeated imports reuse the existing URL. Imported jobs use the existing matching and tracking workflow.

## Evidence and limits

On 2026-10-12, a read-only live smoke check fetched all ten suggested boards: 3,664 postings, zero potential matches and 12 needing review under the strict policy. This is a dated feed snapshot, not a promise of current vacancies. Counts change; no personal account was enrolled by this check.

The cumulative PostgreSQL suite has 32 passing tests. Three real-browser acceptance tests pass, including source creation, schedule execution, shortlist/review separation, a simulated new-posting alert, dismissal, immutable import and pause. Browser provider data is explicitly synthetic and restricted to disposable test databases; production adapters have no fixture switch. Desktop/mobile screenshots were inspected. Deployment, production capacity and always-on hosting remain unverified.
