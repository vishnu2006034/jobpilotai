# Manual jobs and matching v1

Manually entered jobs are private to their user. This deliberately differs from future shared public ATS postings: private notes/descriptions must not accidentally become global. A later discovery module needs a separate public posting identity and provenance mapping.

Jobs are immutable in this release. A user + canonical source URL is unique. URL fragments are removed, while query parameters are retained. Repeating identical input returns the same job; changed details at the same URL return 409. Cross-source deduplication is not implemented. Lists use bounded offset pagination ordered by creation date and ID; concurrent inserts can shift page boundaries.

Eligibility is one of eligible, ineligible or needs_review. A failed explicit restriction wins over missing information. Unreviewed job requirements always require review unless a hard failure is already known. Checking requirements_reviewed means the user checked the original posting and left unrestricted fields blank intentionally. Degree and country comparisons are normalized exact strings, not semantic equivalence. A past deadline is ineligible. Work authorization is self-reported, never inferred from residence. The model currently supports minimum experience, allowed graduation years/degrees, a required authorization country and a deadline; other restrictions require human review.

Score v1 is a prioritization heuristic, not an interview probability:

- Required skill overlap: 70 × matched / required.
- Preferred role text occurs in title: 20, otherwise 0.
- Job is remote or location matches profile exactly: 10, otherwise 0.

Missing required skills make score unavailable rather than giving a perfect skill score. Skills are normalized exact strings; aliases such as JS/JavaScript are not inferred. A high score never overrides hard eligibility. The UI displays missing skills, component points and eligibility separately. Location points express preference only, not legal permission to work remotely.

Each saved match records profile version, scoring version, evaluation time and explanations. Profile edits or crossing a deadline mark old results stale. Jobs cannot be edited yet, so job revision invalidation is not needed in this version. Matching must be rerun before using a stale result.
