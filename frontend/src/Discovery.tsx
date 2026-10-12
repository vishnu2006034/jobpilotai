import { useEffect, useRef, useState } from "react";
import { api, type Job, type Page } from "./api";

type Task = {
  id: string;
  status: string;
  attempt: number;
  error_code: string | null;
  result: Record<string, number | boolean> | null;
};
type Source = {
  id: string;
  provider: string;
  board: string;
  name: string;
  version: number;
  enabled: boolean;
  interval_minutes: number;
  next_run_at: string;
  last_success_at: string | null;
  last_task: Task | null;
};
type Posting = {
  id: string;
  company: string;
  title: string;
  location: string;
  source_url: string;
  description: string;
  first_seen_at: string;
  last_seen_at: string;
  missing_since: string | null;
  revision: number;
  target: { status: string; reasons: string[] };
  salary: {
    currency: string;
    interval: string;
    min: number | null;
    max: number | null;
  } | null;
};
type Notice = {
  id: string;
  source_name: string;
  potential_count: number;
  review_count: number;
  created_at: string;
};
type Notices = { unread_count: number; items: Notice[] };
const when = (value: string) => new Date(value).toLocaleString();

export function DiscoveryAlerts({ onOpen }: { onOpen: () => void }) {
  const [notices, setNotices] = useState<Notices>({
    unread_count: 0,
    items: [],
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    let cancelled = false;
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      const request = generation.current;
      try {
        const result = await api<Notices>("/discovery-notices");
        if (!cancelled && request === generation.current) {
          setNotices(result);
          setError("");
        }
      } catch {
        if (!cancelled)
          setError("New-role alerts are temporarily unavailable.");
      } finally {
        loading = false;
      }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  if (error)
    return (
      <p className="hint" role="status">
        {error}
      </p>
    );
  if (!notices.items.length) return null;
  const first = notices.items[0];
  return (
    <section
      className="discovery-alert"
      aria-label="New role alerts"
      aria-live="polite"
    >
      <div>
        <strong>New roles detected at {first.source_name}</strong>
        <p>
          {first.potential_count} potential matches · {first.review_count} need
          details checked.{" "}
          {notices.unread_count > 1 &&
            `${notices.unread_count} unread source updates.`}
        </p>
      </div>
      <button className="secondary" onClick={onOpen}>
        Open discovery
      </button>
      <button
        className="text-link"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          generation.current++;
          try {
            await api(`/discovery-notices/${first.id}/read`, "POST");
            setNotices(await api<Notices>("/discovery-notices"));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        Dismiss this update
      </button>
    </section>
  );
}

export function DiscoveryWorkspace({
  onImport,
}: {
  onImport: (job: Job) => Promise<void>;
}) {
  const [sources, setSources] = useState<Source[]>([]);
  const [postings, setPostings] = useState<Page<Posting>>({
    items: [],
    next_offset: null,
  });
  const [status, setStatus] = useState("potential_match");
  const [selected, setSelected] = useState<Posting | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const request = useRef(0);
  const busyRef = useRef(false);
  const pendingCommands = useRef<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    let loadingPoll = false;
    const id = ++request.current;
    setLoading(true);
    setSelected(null);
    setPostings({ items: [], next_offset: null });
    const load = async () => {
      if (loadingPoll || busyRef.current) return;
      loadingPoll = true;
      try {
        const [s, p] = await Promise.all([
          api<{ items: Source[] }>("/sources"),
          api<Page<Posting>>(`/discovered-postings?status=${status}`),
        ]);
        if (!cancelled && id === request.current) {
          setSources(s.items);
          setPostings((current) => (current.items.length > 30 ? current : p));
          setError("");
        }
      } catch (e) {
        if (!cancelled && id === request.current)
          setError((e as Error).message);
      } finally {
        loadingPoll = false;
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [status, refreshKey]);

  async function act(action: () => Promise<void>, refresh = true) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      if (refresh) setRefreshKey((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="discovery-workspace">
      <div className="discovery-policy">
        <strong>Your search brief</strong>
        <p>
          SDE & data analysis · Fresher / 2027 signals · Chennai on-site or
          India-compatible remote · Bengaluru only with a posted minimum of ₹8
          LPA.
        </p>
        <small>
          Text signals suggest roles to investigate, not confirmed eligibility.
          Unknown pay or remote restrictions stay in review. Sources are checked
          every 15 minutes by default while your scheduler and worker run.
        </small>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <section className="panel source-panel" aria-label="Company sources">
        <div className="section-title">
          <div>
            <h2>Follow company job boards</h2>
            <p className="hint">
              Public Greenhouse and Lever feeds. This is a supported starting
              list, not coverage of every MNC.
            </p>
          </div>
          <div className="source-actions">
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/sources/presets", "POST");
                  setMessage(
                    "Suggested sources added. Your running scheduler will queue their first checks.",
                  );
                })
              }
            >
              Add suggested companies
            </button>
            <button
              className="text-link"
              onClick={() => setShowForm((v) => !v)}
            >
              {showForm ? "Close form" : "+ Add a source"}
            </button>
          </div>
        </div>
        {showForm && (
          <form
            className="source-form"
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void act(async () => {
                await api("/sources", "POST", {
                  provider: data.get("provider"),
                  board: data.get("board"),
                  name: data.get("name"),
                  interval_minutes: Number(data.get("interval_minutes")),
                });
                setShowForm(false);
                setMessage("Source added. The initial check is due now.");
              });
            }}
          >
            <label className="field">
              Company name
              <input name="name" required maxLength={160} />
            </label>
            <label className="field">
              Provider
              <select name="provider" aria-label="Provider">
                <option value="greenhouse">Greenhouse</option>
                <option value="lever">Lever</option>
                <option value="lever_eu">Lever EU</option>
              </select>
            </label>
            <label className="field">
              Board name
              <input
                name="board"
                required
                pattern="[A-Za-z0-9_-]{1,100}"
                placeholder="Company board slug, not a URL"
              />
            </label>
            <label className="field">
              Check interval
              <select name="interval_minutes" aria-label="Check interval">
                <option value="15">Every 15 minutes</option>
                <option value="30">Every 30 minutes</option>
                <option value="60">Every hour</option>
              </select>
            </label>
            <button className="primary" disabled={busy}>
              Add source
            </button>
          </form>
        )}
        {sources.length === 0 && !loading && (
          <p className="muted">
            No company sources yet. Add the verified starting list or a
            supported company board.
          </p>
        )}
        <div className="source-list">
          {sources.map((source) => (
            <article
              key={source.id}
              className="source-row"
              aria-label={`${source.name} source`}
            >
              <div>
                <strong>{source.name}</strong>
                <small>
                  {source.provider} / {source.board} ·{" "}
                  {source.enabled
                    ? `Every ${source.interval_minutes} minutes`
                    : "Paused"}
                </small>
                <small>
                  {source.last_success_at
                    ? `Last success: ${when(source.last_success_at)}`
                    : "No successful check yet"}
                </small>
                {source.last_task && (
                  <small
                    className={
                      source.last_task.status === "failed"
                        ? "source-failed"
                        : ""
                    }
                  >
                    Last run: {source.last_task.status} · attempt{" "}
                    {source.last_task.attempt}
                    {source.last_task.error_code &&
                      ` · ${source.last_task.error_code.replaceAll("_", " ")}`}
                    {source.last_task.result?.fetched !== undefined &&
                      ` · ${source.last_task.result.fetched} postings checked`}
                  </small>
                )}
                {source.last_task?.status === "queued" && (
                  <small>
                    Waiting for a worker. Start the worker if this persists.
                  </small>
                )}
              </div>
              <div className="source-actions">
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    !source.enabled ||
                    ["queued", "running"].includes(
                      source.last_task?.status || "",
                    )
                  }
                  onClick={() =>
                    void act(async () => {
                      const command = (pendingCommands.current[source.id] ||=
                        crypto.randomUUID());
                      await api("/discovery-runs", "POST", {
                        source_id: source.id,
                        command_id: command,
                      });
                      delete pendingCommands.current[source.id];
                      setMessage(`Check queued for ${source.name}.`);
                    })
                  }
                >
                  Check now
                </button>
                <button
                  className="text-link"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await api(`/sources/${source.id}`, "PATCH", {
                        expected_version: source.version,
                        enabled: !source.enabled,
                        interval_minutes: source.interval_minutes,
                      });
                      setMessage(
                        source.enabled
                          ? "Schedule paused. Already running checks may finish."
                          : "Schedule resumed.",
                      );
                    })
                  }
                >
                  {source.enabled ? "Pause" : "Resume"}
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
      <div className="section-bar">
        <div className="tabs">
          {[
            ["potential_match", "Potential matches"],
            ["needs_review", "Needs review"],
            ["all", "All open roles"],
          ].map(([value, title]) => (
            <button
              key={value}
              className={status === value ? "selected" : ""}
              onClick={() => setStatus(value)}
            >
              {title}
            </button>
          ))}
        </div>
        <button
          className="text-link"
          disabled={busy}
          onClick={() => setRefreshKey((value) => value + 1)}
        >
          Refresh results
        </button>
      </div>
      <div className="jobs-layout">
        <section className="job-list" aria-label="Discovered roles">
          {loading ? (
            <p className="muted">Loading discovered roles…</p>
          ) : postings.items.length === 0 ? (
            <div className="empty">
              <span>⌁</span>
              <h2>No roles in this view yet.</h2>
              <p>
                Check your sources and the review tab. We won’t invent salary,
                eligibility, or vacancies to fill the shortlist.
              </p>
            </div>
          ) : (
            postings.items.map((posting) => (
              <article
                key={posting.id}
                className={`job-card ${selected?.id === posting.id ? "focused" : ""}`}
              >
                <div className="company-icon">
                  {posting.company.slice(0, 2).toUpperCase()}
                </div>
                <div className="job-main">
                  <div className="job-meta">
                    {posting.company}
                    <span>Detected {when(posting.first_seen_at)}</span>
                  </div>
                  <button
                    className="job-title"
                    onClick={() => setSelected(posting)}
                  >
                    {posting.title}
                  </button>
                  <p>{posting.location || "Location not stated"}</p>
                  <div className="chips">
                    <span
                      className={
                        posting.target.status === "needs_review" ? "amber" : ""
                      }
                    >
                      {posting.target.status.replaceAll("_", " ")}
                    </span>
                    {posting.missing_since && (
                      <span className="amber">Missing from latest check</span>
                    )}
                  </div>
                </div>
              </article>
            ))
          )}
          {postings.next_offset !== null && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const id = request.current;
                  const next = await api<Page<Posting>>(
                    `/discovered-postings?status=${status}&offset=${postings.next_offset}`,
                  );
                  if (id === request.current)
                    setPostings((current) => ({
                      items: [
                        ...current.items,
                        ...next.items.filter(
                          (item) =>
                            !current.items.some((old) => old.id === item.id),
                        ),
                      ],
                      next_offset: next.next_offset,
                    }));
                }, false)
              }
            >
              Load more roles
            </button>
          )}
        </section>
        <aside className="detail-panel">
          {selected ? (
            <>
              <p className="eyebrow">FROM THE COMPANY BOARD</p>
              <h2>{selected.title}</h2>
              <p className="muted">
                {selected.company} · {selected.location}
              </p>
              <a
                className="text-link"
                href={selected.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Read original posting ↗
              </a>
              <ul className="target-reasons">
                {selected.target.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              {selected.salary && (
                <p className="hint">
                  Posted range: {selected.salary.currency}{" "}
                  {selected.salary.min?.toLocaleString() ?? "unknown"}–
                  {selected.salary.max?.toLocaleString() ?? "unknown"} (
                  {selected.salary.interval}). This is not an offer.
                </p>
              )}
              <p className="description">
                {selected.description || "Read the source for full details."}
              </p>
              <p className="hint">
                Last seen {when(selected.last_seen_at)} · snapshot{" "}
                {selected.revision}. Detection time is not the company’s
                publication time.
              </p>
              <button
                className="primary full"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const job = await api<
                      Job & { already_in_workspace: boolean }
                    >(`/discovered-postings/${selected.id}/import`, "POST");
                    await onImport(job);
                  }, false)
                }
              >
                Add to my opportunities
              </button>
              <p className="hint">
                Saves a private copy for matching and tracking. Existing copies
                are kept unchanged. No application is submitted.
              </p>
            </>
          ) : (
            <>
              <div className="compass">⌁</div>
              <h2>A focused watchlist.</h2>
              <p className="muted">
                Select a role to inspect the posted details and see why it
                matches—or needs review.
              </p>
              <p className="hint">
                First checks establish a baseline. Later newly detected roles
                create an in-app alert. Keep the backend scheduler and worker
                running; this is not instant push or a closed-browser
                notification service.
              </p>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
