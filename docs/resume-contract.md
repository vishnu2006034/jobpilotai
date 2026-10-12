# Resume text versions and focused drafts

Implemented 2026-10-12 as the first resume-preparation module. This is user-directed text selection, not AI rewriting or automatic resume extraction.

## Workflow

Open Resumes, paste plain text or read a UTF-8 `.txt` file, name the version and save. Separate paragraphs with blank lines. Check the complete saved version and confirm its facts. Choose a saved opportunity and select the paragraphs to retain. Create the draft, inspect its complete preview, confirm that exact draft, and download the reviewed `.txt` file.

Draft creation uses only complete source paragraphs, preserving their wording and source order. It does not infer qualifications, add job keywords, generate achievements, update the profile, or submit an application. Selection can remove important context, so source review and final draft review are separate steps. Human confirmation records the user's assertion, not independent fact verification.

## Persistence and ownership

- Text versions and draft content are immutable through the API. Changed text creates a new version; it never changes prior drafts or their reviews. Line endings are normalized to LF and outer whitespace trimmed before hashing. Original file bytes and filenames are not archived.
- A SHA-256 digest deduplicates source text within an account. Reimporting identical normalized text returns the existing version, including its original name and review state. A new title alone is not a new version.
- A draft digest includes the source version identity, source digest, target immutable job identity and exact selected text. Recreating the same draft returns it; different content or target needs a new review.
- Review requires the exact digest. Downloads require review and authenticated ownership; responses are text attachments with no-store and nosniff headers. No public file URLs exist.
- Compound foreign keys enforce ownership of both source and target job. Account row locking serializes duplicate saves, review writes and quota checks. This is API immutability, not protection against a database administrator changing rows.
- Limits: 50,000 characters / 200,000 UTF-8 bytes per version, 500 paragraphs, 100 versions and 500 drafts per account. Unsupported controls and unknown input fields are rejected. Records are private PostgreSQL data, not repository files. There is no per-record deletion or retention UI yet.

## Scope still pending

PDF/DOCX parsing, original binary retention, parser isolation, structured profile-fact extraction, AI-assisted rewriting, formatted PDF output and submission approval remain unimplemented. Resume review is not submission authorization. This module does not call an LLM or an external document service.

## Verification

36 cumulative PostgreSQL tests pass, including concurrent duplicate import, cross-account access rejection, source review requirements, invalid paragraph rejection, rejection of injected free-form draft claims, exact-content review, export and preservation after new source versions. Four Chrome acceptance tests pass, including UTF-8 file input, paragraph exclusion, draft download byte comparison, reload persistence and mobile overflow checks. Desktop/mobile screenshots use synthetic data and were inspected. One upstream Starlette/AnyIO deprecation warning remains.
