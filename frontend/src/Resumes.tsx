import { useEffect, useRef, useState } from "react";
import { api, Job, Page } from "./api";

type Version = {
  id: string;
  title: string;
  text: string;
  digest: string;
  blocks: string[];
  reviewed_at: string | null;
};
type Draft = {
  id: string;
  resume_id: string;
  job_id: string;
  text: string;
  digest: string;
  reviewed_at: string | null;
};

export function ResumeWorkspace() {
  const [versions, setVersions] = useState<Version[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [jobs, setJobs] = useState<Page<Job>>({ items: [], next_offset: null });
  const [selected, setSelected] = useState<Version | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [job, setJob] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  async function act(work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Version[]>("/resumes"),
      api<Draft[]>("/resumes/drafts"),
      api<Page<Job>>("/jobs"),
    ])
      .then(([v, d, j]) => {
        if (active) {
          setVersions(v);
          setDrafts(d);
          setJobs(j);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  function choose(v: Version) {
    setSelected(v);
    setChosen(v.blocks.map((_, i) => i));
    setDraft(null);
  }
  async function refresh() {
    setVersions(await api<Version[]>("/resumes"));
    setDrafts(await api<Draft[]>("/resumes/drafts"));
  }
  return (
    <div className="resume-workspace">
      <section className="search-policy">
        <h2>Your words, with a clearer focus.</h2>
        <p>
          Save text versions, review your facts, and choose relevant paragraphs
          for a job. Drafts retain your original wording and order. Nothing is
          submitted.
        </p>
        <small>
          Text-only import for now. PDF/DOCX extraction, AI rewriting and
          automatic profile updates are not included.
        </small>
      </section>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      <form
        className="panel resume-panel"
        onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            const v = await api<Version>("/resumes", "POST", { title, text });
            choose(v);
            await refresh();
            setTitle("");
            setText("");
            setNotice(
              "Saved immutable text version. Review it before drafting.",
            );
          });
        }}
      >
        <h2>Import a text version</h2>
        <label>
          Version name
          <input
            required
            maxLength={120}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          Read a UTF-8 .txt file
          <input
            type="file"
            accept=".txt,text/plain"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file)
                void act(async () => {
                  if (
                    !file.name.toLowerCase().endsWith(".txt") ||
                    file.size > 200000
                  )
                    throw new Error(
                      "Choose a UTF-8 .txt file no larger than 200 KB.",
                    );
                  const value = new TextDecoder("utf-8", {
                    fatal: true,
                  }).decode(await file.arrayBuffer());
                  if (value.length > 50000)
                    throw new Error("Use at most 50,000 characters.");
                  setText(value);
                  if (!title) setTitle(file.name.replace(/\.txt$/i, ""));
                });
            }}
          />
        </label>
        <label>
          Resume text
          <textarea
            required
            maxLength={50000}
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <p className="muted">
          Separate paragraphs with a blank line. Changes are saved as new
          versions; original versions remain unchanged.
        </p>
        <button className="primary" disabled={busy}>
          Save text version
        </button>
      </form>
      <div className="resume-columns">
        <section className="panel resume-panel">
          <h2>Saved versions</h2>
          {!versions.length && (
            <p className="muted">Import your first text version above.</p>
          )}
          {versions.map((v) => (
            <button
              className="resume-choice"
              key={v.id}
              disabled={busy}
              aria-pressed={selected?.id === v.id}
              onClick={() => choose(v)}
            >
              {v.title}
              <small>
                {v.reviewed_at ? "Reviewed by you" : "Needs your review"}
              </small>
            </button>
          ))}
        </section>
        <section className="panel resume-panel">
          <h2>Prepare for an opportunity</h2>
          {!selected ? (
            <p className="muted">
              Choose a saved version to review its content.
            </p>
          ) : (
            <>
              <h3>{selected.title}</h3>
              <p>
                Check every fact before confirming. Select complete paragraphs
                to retain in your draft.
              </p>
              {selected.blocks.map((b, i) => (
                <label className="resume-block" key={i}>
                  <input
                    type="checkbox"
                    checked={chosen.includes(i)}
                    disabled={busy}
                    onChange={(e) =>
                      setChosen(
                        e.target.checked
                          ? [...chosen, i]
                          : chosen.filter((n) => n !== i),
                      )
                    }
                  />
                  <span>{b}</span>
                </label>
              ))}
              {!selected.reviewed_at && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      setSelected(
                        await api<Version>(
                          `/resumes/${selected.id}/review`,
                          "POST",
                          { digest: selected.digest },
                        ),
                      );
                      await refresh();
                    })
                  }
                >
                  I reviewed this version’s facts
                </button>
              )}
              <label>
                Target opportunity
                <select
                  aria-label="Target opportunity"
                  value={job}
                  onChange={(e) => setJob(e.target.value)}
                >
                  <option value="">Choose an opportunity</option>
                  {jobs.items.map((j) => (
                    <option value={j.id} key={j.id}>
                      {j.company} — {j.title}
                    </option>
                  ))}
                </select>
              </label>
              {jobs.next_offset !== null && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      const more = await api<Page<Job>>(
                        `/jobs?offset=${jobs.next_offset}`,
                      );
                      setJobs({
                        items: [...jobs.items, ...more.items],
                        next_offset: more.next_offset,
                      });
                    })
                  }
                >
                  Load more opportunities
                </button>
              )}
              <button
                className="primary"
                disabled={
                  busy || !selected.reviewed_at || !job || !chosen.length
                }
                onClick={() =>
                  void act(async () => {
                    setDraft(
                      await api<Draft>("/resumes/drafts", "POST", {
                        resume_id: selected.id,
                        job_id: job,
                        selected_blocks: chosen,
                      }),
                    );
                    await refresh();
                    setNotice(
                      "Draft saved. Review the complete preview before downloading.",
                    );
                  })
                }
              >
                Create focused draft
              </button>
            </>
          )}
        </section>
      </div>
      <section className="panel resume-panel">
        <h2>Saved drafts</h2>
        <p className="muted">
          Review confirms this exact text. It does not authorize an application
          submission. New drafts require a new review.
        </p>
        {!drafts.length && <p>No drafts yet.</p>}
        <div className="resume-drafts">
          {drafts.map((d) => (
            <button
              key={d.id}
              aria-pressed={draft?.id === d.id}
              onClick={() => setDraft(d)}
            >
              {jobs.items.find((j) => j.id === d.job_id)?.title ||
                "Saved opportunity"}{" "}
              · {d.reviewed_at ? "Reviewed" : "Needs review"}
              <small>Draft {d.id.slice(0, 8)}</small>
            </button>
          ))}
        </div>
        {draft && (
          <div aria-label="Draft preview">
            <h3>Draft preview</h3>
            <pre className="resume-preview">{draft.text}</pre>
            {!draft.reviewed_at ? (
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    setDraft(
                      await api<Draft>(
                        `/resumes/drafts/${draft.id}/review`,
                        "POST",
                        { digest: draft.digest },
                      ),
                    );
                    await refresh();
                  })
                }
              >
                I reviewed this exact draft
              </button>
            ) : (
              <a
                className="primary resume-download"
                href={`/api/v1/resumes/drafts/${draft.id}/download`}
              >
                Download reviewed text
              </a>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
