import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  ApiError,
  type User,
  type Profile,
  type Job,
  type Match,
  type Application,
  type TimelineEvent,
  type Page,
  type Summary,
} from "./api";
import "./style.css";
import { DiscoveryAlerts, DiscoveryWorkspace } from "./Discovery";

const split = (value: FormDataEntryValue | null) =>
  String(value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
const number = (value: FormDataEntryValue | null) =>
  String(value || "").trim() ? Number(value) : null;
const label = (value: string) => value.toLowerCase().replaceAll("_", " ");
const date = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

function Field({
  title,
  children,
  hint,
}: {
  title: string;
  children: React.ReactNode;
  hint?: string;
}) {
  const id = React.useId();
  return (
    <div className="field">
      <label htmlFor={id}>{title}</label>
      {React.cloneElement(
        children as React.ReactElement<{
          id?: string;
          "aria-describedby"?: string;
        }>,
        { id, "aria-describedby": hint ? `${id}-hint` : undefined },
      )}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [screen, setScreen] = useState("jobs");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [jobs, setJobs] = useState<Page<Job>>({ items: [], next_offset: null });
  const [applications, setApplications] = useState<Page<Application>>({
    items: [],
    next_offset: null,
  });
  const [selected, setSelected] = useState<Job | null>(null);
  const [match, setMatch] = useState<Match | null>(null);
  const [selectedApplication, setSelectedApplication] =
    useState<Application | null>(null);
  const [events, setEvents] = useState<Page<TimelineEvent>>({
    items: [],
    next_offset: null,
  });
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const matchRequest = useRef(0);
  const timelineRequest = useRef(0);
  const authGeneration = useRef(0);
  const command = useRef<{ payload: string; id: string } | null>(null);

  useEffect(() => {
    const unauthorized = () => {
      authGeneration.current++;
      matchRequest.current++;
      timelineRequest.current++;
      setUser(null);
      setProfile(null);
      setSelected(null);
      setMatch(null);
      setSelectedApplication(null);
    };
    window.addEventListener("jobpilot:unauthorized", unauthorized);
    api<User>("/me")
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) setError(e.message);
      })
      .finally(() => setBooting(false));
    return () =>
      window.removeEventListener("jobpilot:unauthorized", unauthorized);
  }, []);

  async function refresh() {
    const generation = authGeneration.current;
    const [p, s, j, a] = await Promise.all([
      api<Profile>("/profile"),
      api<Summary>("/dashboard/summary"),
      api<Page<Job>>("/jobs"),
      api<Page<Application>>("/applications"),
    ]);
    if (generation !== authGeneration.current) return;
    setProfile(p);
    setSummary(s);
    setJobs(j);
    setApplications(a);
  }
  useEffect(() => {
    if (user) refresh().catch((e) => setError(e.message));
  }, [user?.id]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function selectJob(job: Job) {
    const request = ++matchRequest.current;
    setSelected(job);
    setMatch(null);
    setError("");
    try {
      const result = await api<Match>(`/jobs/${job.id}/match`);
      if (request === matchRequest.current) setMatch(result);
    } catch (e) {
      if (
        request === matchRequest.current &&
        !(e instanceof ApiError && e.status === 404)
      )
        setError((e as Error).message);
    }
  }

  async function selectApplication(application: Application) {
    const request = ++timelineRequest.current;
    command.current = null;
    setSelectedApplication(application);
    setEvents({ items: [], next_offset: null });
    try {
      const result = await api<Page<TimelineEvent>>(
        `/applications/${application.id}/events`,
      );
      if (request === timelineRequest.current) setEvents(result);
    } catch (e) {
      if (request === timelineRequest.current) setError((e as Error).message);
    }
  }

  if (booting) return <div className="loading">Opening your workspace…</div>;
  if (!user)
    return (
      <div className="auth-layout">
        <div className="auth-story">
          <Logo />
          <div>
            <p className="eyebrow">A LITTLE DIRECTION. A BIG NEXT STEP.</p>
            <h1>
              Your next chapter
              <br />
              starts here.
            </h1>
            <p>
              Keep your opportunities, your progress, and your next move in one
              thoughtful workspace.
            </p>
          </div>
          <span>Built for a more intentional job search.</span>
        </div>
        <main className="auth-form">
          <p className="eyebrow">WELCOME TO JOBPILOT</p>
          <h2>Make room for what’s next.</h2>
          <p className="muted">Sign in to your personal workspace.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void run(async () => {
                const loggedIn = await api<User>(
                  "/auth/login",
                  "POST",
                  Object.fromEntries(data),
                );
                authGeneration.current++;
                setUser(loggedIn);
              });
            }}
          >
            <Field title="Email">
              <input
                name="email"
                type="email"
                autoComplete="username"
                required
              />
            </Field>
            <Field title="Password">
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </Field>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button className="primary" disabled={busy}>
              {busy ? "Signing in…" : "Sign in →"}
            </button>
          </form>
          <p className="setup-hint">
            First time? Create your local account using the setup guide in the
            project README.
          </p>
        </main>
      </div>
    );

  const visibleJobs = jobs.items.filter(
    (j) =>
      (filter !== "saved" || j.saved) &&
      `${j.title} ${j.company} ${j.location}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Logo />
        <p className="nav-caption">YOUR WORKSPACE</p>
        <nav aria-label="Main navigation">
          {[
            ["jobs", "◈", "Opportunities"],
            ["discovery", "⌁", "Discovery"],
            ["applications", "▤", "Applications"],
            ["profile", "◎", "My profile"],
          ].map(([id, icon, name]) => (
            <button
              key={id}
              className={screen === id ? "nav-link active" : "nav-link"}
              aria-current={screen === id ? "page" : undefined}
              onClick={() => {
                setScreen(id);
                setError("");
                setNotice("");
              }}
            >
              <span aria-hidden>{icon}</span>
              {name}
              {id === "applications" && <b>{summary?.applications ?? 0}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="little-star">✧</span>
          <strong>One step at a time.</strong>
          <p>A thoughtful application beats a hundred hurried ones.</p>
        </div>
        <div className="account">
          <div className="avatar">
            {(profile?.full_name || user.email).slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{profile?.full_name || "Your workspace"}</strong>
            <small>{user.email}</small>
          </div>
          <button
            aria-label="Sign out"
            title="Sign out"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api("/auth/logout", "POST");
                authGeneration.current++;
                matchRequest.current++;
                timelineRequest.current++;
                setUser(null);
                setProfile(null);
                setJobs({ items: [], next_offset: null });
                setApplications({ items: [], next_offset: null });
                setSelected(null);
                setMatch(null);
                setSelectedApplication(null);
              })
            }
          >
            ↗
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>
            Personal workspace <span className="slash">/</span>{" "}
            {screen === "jobs"
              ? "Opportunities"
              : screen === "applications"
                ? "Applications"
                : screen === "discovery"
                  ? "Discovery"
                  : "My profile"}
          </span>
          <span className="local-status">
            <i /> Local workspace
          </span>
          <button
            className="mobile-signout"
            aria-label="Sign out on mobile"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api("/auth/logout", "POST");
                authGeneration.current++;
                matchRequest.current++;
                timelineRequest.current++;
                setUser(null);
                setProfile(null);
                setSelected(null);
                setMatch(null);
                setSelectedApplication(null);
              })
            }
          >
            Sign out
          </button>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {screen === "jobs"
                  ? "FIND YOUR NEXT CHAPTER"
                  : screen === "applications"
                    ? "EVERY STEP, IN ONE PLACE"
                    : screen === "discovery"
                      ? "YOUR NEXT ROLE, ON THE RADAR"
                      : "A PROFILE THAT SOUNDS LIKE YOU"}
              </p>
              <h1>
                {screen === "jobs"
                  ? "Good things ahead."
                  : screen === "applications"
                    ? "Keep your momentum."
                    : screen === "discovery"
                      ? "Stay close to what’s next."
                      : "Start with your strengths."}
              </h1>
              <p className="muted">
                {screen === "jobs"
                  ? "A considered shortlist. A clearer path to your next role."
                  : screen === "applications"
                    ? "Track the applications you make, and know what comes next."
                    : screen === "discovery"
                      ? "Follow company boards and catch new roles that deserve a closer look."
                      : "Your details power transparent, practical job matches."}
              </p>
            </div>
            {screen === "jobs" && (
              <button
                className="primary"
                disabled={busy}
                onClick={() => setAdding(true)}
              >
                + Add opportunity
              </button>
            )}
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <DiscoveryAlerts
            key={`alerts-${user.id}`}
            onOpen={() => setScreen("discovery")}
          />
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          <section className="stats" aria-label="Workspace overview">
            {[
              ["Opportunities", summary?.jobs, "In your workspace"],
              ["Saved for later", summary?.saved_jobs, "Worth a closer look"],
              ["Applications", summary?.applications, "Steps you’ve taken"],
              [
                "Interviews",
                summary?.by_state.INTERVIEW || 0,
                "Conversations ahead",
              ],
            ].map(([name, value, description]) => (
              <div className="stat" key={String(name)}>
                <span>{name}</span>
                <strong>{value ?? "—"}</strong>
                <small>{description}</small>
              </div>
            ))}
          </section>

          {screen === "discovery" && (
            <DiscoveryWorkspace
              key={`discovery-${user.id}`}
              onImport={async (job) => {
                await refresh();
                await selectJob(job);
                setScreen("jobs");
                setNotice(
                  "Opened the saved opportunity. Review its requirements before relying on a match.",
                );
              }}
            />
          )}

          {screen === "jobs" && (
            <>
              <div className="section-bar">
                <div className="tabs">
                  <button
                    className={filter === "all" ? "selected" : ""}
                    onClick={() => setFilter("all")}
                  >
                    All opportunities
                  </button>
                  <button
                    className={filter === "saved" ? "selected" : ""}
                    onClick={() => setFilter("saved")}
                  >
                    Saved
                  </button>
                </div>
                <input
                  className="search"
                  aria-label="Search loaded opportunities"
                  placeholder="Search loaded opportunities…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div className="jobs-layout">
                <section className="job-list" aria-label="Opportunities">
                  {visibleJobs.length === 0 ? (
                    <div className="empty">
                      <span>↗</span>
                      <h2>
                        {jobs.items.length
                          ? "No matching opportunities"
                          : "Your next opportunity starts here"}
                      </h2>
                      <p>
                        {jobs.items.length
                          ? "Try another search or switch to all opportunities."
                          : "Found a role you like? Add its details to compare it with your profile and track your progress."}
                      </p>
                      {!jobs.items.length && (
                        <button
                          className="secondary"
                          onClick={() => setAdding(true)}
                        >
                          Add your first opportunity
                        </button>
                      )}
                    </div>
                  ) : (
                    visibleJobs.map((job) => (
                      <article
                        key={job.id}
                        className={`job-card ${selected?.id === job.id ? "focused" : ""}`}
                      >
                        <div className="company-icon">
                          {job.company.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="job-main">
                          <div className="job-meta">
                            {job.company}
                            <span>
                              {job.provenance === "ats_snapshot"
                                ? `${job.source_details.provider} snapshot`
                                : "Manually added"}
                            </span>
                          </div>
                          <button
                            className="job-title"
                            onClick={() => void selectJob(job)}
                          >
                            {job.title}
                          </button>
                          <p>
                            {job.location || "Location unspecified"}{" "}
                            <span>·</span>{" "}
                            {job.remote ? "Remote" : "Work mode not specified"}
                          </p>
                          <div className="chips">
                            {job.required_skills.slice(0, 4).map((skill) => (
                              <span key={skill}>{skill}</span>
                            ))}
                            {!job.requirements_reviewed && (
                              <span className="amber">
                                Requirements need review
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          className={`save-button ${job.saved ? "saved" : ""}`}
                          disabled={busy}
                          aria-label={`${job.saved ? "Unsave" : "Save"} ${job.title}`}
                          onClick={() =>
                            void run(async () => {
                              await api(
                                `/jobs/${job.id}/save`,
                                job.saved ? "DELETE" : "POST",
                              );
                              if (selected?.id === job.id)
                                setSelected({ ...job, saved: !job.saved });
                              await refresh();
                            })
                          }
                        >
                          {job.saved ? "★" : "☆"}
                        </button>
                      </article>
                    ))
                  )}
                  {jobs.next_offset !== null && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const next = await api<Page<Job>>(
                            `/jobs?offset=${jobs.next_offset}`,
                          );
                          setJobs({
                            items: [...jobs.items, ...next.items],
                            next_offset: next.next_offset,
                          });
                        })
                      }
                    >
                      Load more opportunities
                    </button>
                  )}
                </section>
                <aside className="detail-panel">
                  {selected ? (
                    <>
                      <p className="eyebrow">A CLOSER LOOK</p>
                      <h2>{selected.title}</h2>
                      <p className="muted">{selected.company}</p>
                      <a
                        className="text-link"
                        href={selected.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        View original posting ↗
                      </a>
                      <p className="description">
                        {selected.description || "No description added."}
                      </p>
                      <button
                        className="secondary full"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const id = selected.id;
                            const request = ++matchRequest.current;
                            const result = await api<Match>(
                              `/jobs/${id}/match`,
                              "POST",
                            );
                            if (request === matchRequest.current)
                              setMatch(result);
                          })
                        }
                      >
                        {match ? "Recalculate fit" : "Check my fit"}
                      </button>
                      {match && (
                        <div className="match" aria-label="Match result">
                          <div className="match-top">
                            <span
                              className={`badge ${match.stale ? "needs_review" : match.eligibility}`}
                            >
                              {match.stale
                                ? "Out of date — recalculate"
                                : label(match.eligibility)}
                            </span>
                            <strong>
                              {match.stale
                                ? "—"
                                : match.score === null
                                  ? "N/A"
                                  : `${match.score}/100`}
                            </strong>
                          </div>
                          <p className="hint">
                            Fit score, not a hiring probability. Eligibility is
                            assessed separately.
                          </p>
                          <ul>
                            {match.reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                          <p>
                            <strong>Skill gaps:</strong>{" "}
                            {match.skill_gaps.join(", ") || "None recorded"}
                          </p>
                          <small>
                            Skills {match.components.skills_out_of_70 ?? "N/A"}
                            /70 · Role {match.components.role_out_of_20}/20 ·
                            Location {match.components.location_out_of_10}/10
                          </small>
                        </div>
                      )}
                      <button
                        className="primary full"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const a = await api<Application>(
                              "/applications",
                              "POST",
                              { job_id: selected.id },
                            );
                            await refresh();
                            await selectApplication(a);
                            setScreen("applications");
                            setNotice(
                              "Tracking started. No application has been submitted.",
                            );
                          })
                        }
                      >
                        Track this application →
                      </button>
                      <p className="hint">
                        You apply on the company’s site. JobPilot records your
                        progress.
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="compass">✧</div>
                      <p className="eyebrow">A LITTLE MORE CLARITY</p>
                      <h2>Find your fit.</h2>
                      <p className="muted">
                        Choose an opportunity to see how it lines up with your
                        skills and preferences.
                      </p>
                      <div className="detail-tip">
                        <strong>Make it personal</strong>
                        <p>
                          Add your skills and graduation year for more useful
                          matches.
                        </p>
                        <button
                          className="text-link"
                          onClick={() => setScreen("profile")}
                        >
                          Complete your profile →
                        </button>
                      </div>
                    </>
                  )}
                </aside>
              </div>
              <div className="roadmap-note">
                <span>ON THE HORIZON</span> Resume tailoring, Gmail sync, and
                application submission are not available in this version.
              </div>
            </>
          )}

          {screen === "profile" &&
            (profile ? (
              <form
                className="panel profile-form"
                key={profile.version}
                onSubmit={(e) => {
                  e.preventDefault();
                  const data = new FormData(e.currentTarget);
                  void run(async () => {
                    const updated = await api<Profile>("/profile", "PATCH", {
                      full_name: data.get("full_name"),
                      degree: data.get("degree"),
                      location: data.get("location"),
                      graduation_year: number(data.get("graduation_year")),
                      experience_years: number(data.get("experience_years")),
                      skills: split(data.get("skills")),
                      preferred_roles: split(data.get("preferred_roles")),
                      authorized_countries: split(
                        data.get("authorized_countries"),
                      ),
                      expected_version: profile.version,
                    });
                    setProfile(updated);
                    if (match) setMatch({ ...match, stale: true });
                    setNotice(
                      "Profile saved. Recalculate existing matches to use your new details.",
                    );
                  });
                }}
              >
                <h2>Your story, at a glance.</h2>
                <p className="muted">
                  Leave unknown details blank. We won’t guess your
                  qualifications.
                </p>
                <div className="form-grid">
                  <Field title="Full name">
                    <input
                      name="full_name"
                      defaultValue={profile.full_name}
                      maxLength={120}
                    />
                  </Field>
                  <Field title="Graduation year">
                    <input
                      name="graduation_year"
                      type="number"
                      min={1950}
                      max={2100}
                      defaultValue={profile.graduation_year ?? ""}
                    />
                  </Field>
                  <Field title="Degree">
                    <input
                      name="degree"
                      defaultValue={profile.degree}
                      maxLength={120}
                    />
                  </Field>
                  <Field title="Years of experience">
                    <input
                      name="experience_years"
                      type="number"
                      min={0}
                      max={60}
                      step="0.1"
                      defaultValue={profile.experience_years ?? ""}
                    />
                  </Field>
                  <Field title="Location">
                    <input
                      name="location"
                      defaultValue={profile.location}
                      maxLength={120}
                    />
                  </Field>
                  <Field
                    title="Authorized work countries"
                    hint="Use country names matching job requirements, separated by commas."
                  >
                    <input
                      name="authorized_countries"
                      defaultValue={profile.authorized_countries.join(", ")}
                    />
                  </Field>
                </div>
                <Field
                  title="Skills"
                  hint="Separate with commas. Example: Python, SQL, React"
                >
                  <input
                    name="skills"
                    defaultValue={profile.skills.join(", ")}
                  />
                </Field>
                <Field
                  title="Preferred roles"
                  hint="Separate with commas. Example: engineer, analyst"
                >
                  <input
                    name="preferred_roles"
                    defaultValue={profile.preferred_roles.join(", ")}
                  />
                </Field>
                <button className="primary" disabled={busy}>
                  Save profile
                </button>
                <button
                  type="button"
                  className="text-link"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      setProfile(await api<Profile>("/profile"));
                      setNotice("Loaded the latest profile.");
                    })
                  }
                >
                  Reload saved profile
                </button>
              </form>
            ) : (
              <p>Loading profile…</p>
            ))}

          {screen === "applications" && (
            <div className="jobs-layout">
              <section className="job-list">
                <div className="section-title">
                  <h2>Your application journey</h2>
                  <span className="muted">Manual tracking</span>
                </div>
                {applications.items.length === 0 ? (
                  <div className="empty">
                    <span>▤</span>
                    <h2>A fresh start.</h2>
                    <p>
                      Open an opportunity and choose “Track this application” to
                      begin your timeline.
                    </p>
                    <button
                      className="secondary"
                      onClick={() => setScreen("jobs")}
                    >
                      Explore opportunities
                    </button>
                  </div>
                ) : (
                  applications.items.map((a) => (
                    <button
                      key={a.id}
                      className={`application-card ${a.id === selectedApplication?.id ? "focused" : ""}`}
                      onClick={() => void selectApplication(a)}
                    >
                      <div className="company-icon">
                        {a.company.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <strong>{a.title}</strong>
                        <p>
                          {a.company} · Updated {date(a.updated_at)}
                        </p>
                      </div>
                      <span className="badge">{label(a.state)}</span>
                    </button>
                  ))
                )}
                {applications.next_offset !== null && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const next = await api<Page<Application>>(
                          `/applications?offset=${applications.next_offset}`,
                        );
                        setApplications({
                          items: [...applications.items, ...next.items],
                          next_offset: next.next_offset,
                        });
                      })
                    }
                  >
                    Load more applications
                  </button>
                )}
              </section>
              <aside className="detail-panel">
                {selectedApplication ? (
                  <>
                    <p className="eyebrow">APPLICATION TIMELINE</p>
                    <h2>{selectedApplication.title}</h2>
                    <p className="muted">{selectedApplication.company}</p>
                    <span className="badge">
                      {label(selectedApplication.state)}
                    </span>
                    {selectedApplication.allowed_transitions.length > 0 && (
                      <form
                        key={`${selectedApplication.id}-${selectedApplication.version}`}
                        className="status-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          const data = new FormData(e.currentTarget);
                          const a = selectedApplication;
                          const payload = {
                            state: data.get("state"),
                            note: data.get("note"),
                            confirmed: data.get("confirmed") === "on",
                            expected_version: a.version,
                          };
                          const serialized = JSON.stringify(payload);
                          if (command.current?.payload !== serialized)
                            command.current = {
                              payload: serialized,
                              id: crypto.randomUUID(),
                            };
                          const id = command.current.id;
                          void run(async () => {
                            const updated = await api<Application>(
                              `/applications/${a.id}/status`,
                              "POST",
                              { ...payload, command_id: id },
                            );
                            await refresh();
                            await selectApplication(updated);
                            setNotice(
                              "Status updated and added to the timeline.",
                            );
                          });
                        }}
                      >
                        <Field title="Next status">
                          <select name="state">
                            {selectedApplication.allowed_transitions.map(
                              (s) => (
                                <option key={s} value={s}>
                                  {label(s)}
                                </option>
                              ),
                            )}
                          </select>
                        </Field>
                        <Field title="What happened?">
                          <textarea
                            name="note"
                            required
                            minLength={3}
                            maxLength={2000}
                            placeholder="Add confirmation details or a short note."
                          />
                        </Field>
                        <label className="checkbox">
                          <input type="checkbox" name="confirmed" />I confirm
                          this status reflects what happened.
                        </label>
                        <button className="primary full" disabled={busy}>
                          Update status
                        </button>
                      </form>
                    )}
                    <button
                      className="text-link"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await selectApplication(
                            await api<Application>(
                              `/applications/${selectedApplication.id}`,
                            ),
                          );
                        })
                      }
                    >
                      Reload latest status
                    </button>
                    <ol className="timeline">
                      {events.items.map((event) => (
                        <li key={event.id}>
                          <strong>{label(event.next_state)}</strong>
                          <small>{date(event.created_at)}</small>
                          <p>{event.evidence.note}</p>
                        </li>
                      ))}
                    </ol>
                    {events.next_offset !== null && (
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const next = await api<Page<TimelineEvent>>(
                              `/applications/${selectedApplication.id}/events?offset=${events.next_offset}`,
                            );
                            setEvents({
                              items: [...events.items, ...next.items],
                              next_offset: next.next_offset,
                            });
                          })
                        }
                      >
                        Older events
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <div className="compass">↗</div>
                    <h2>Every step counts.</h2>
                    <p className="muted">
                      Choose an application to see its history or record your
                      next milestone.
                    </p>
                  </>
                )}
              </aside>
            </div>
          )}
          <footer>
            JobPilot <span>·</span> A little direction for your next big move.
          </footer>
        </div>
      </main>
      {adding && (
        <AddJob
          error={error}
          busy={busy}
          close={() => setAdding(false)}
          submit={(data) =>
            run(async () => {
              const job = await api<Job>("/jobs", "POST", data);
              await refresh();
              setAdding(false);
              await selectJob(job);
              setNotice("Opportunity added to your workspace.");
            })
          }
        />
      )}
    </div>
  );
}

function Logo() {
  return (
    <div className="logo">
      <span>↗</span>JobPilot<i>AI</i>
    </div>
  );
}

function AddJob({
  error,
  busy,
  close,
  submit,
}: {
  error: string;
  busy: boolean;
  close: () => void;
  submit: (data: unknown) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else close();
      }}
    >
      <div className="modal-heading">
        <div>
          <p className="eyebrow">MAKE IT AN OPPORTUNITY</p>
          <h2>Add a role worth exploring.</h2>
        </div>
        <button
          type="button"
          aria-label="Close add opportunity"
          disabled={busy}
          onClick={close}
        >
          ×
        </button>
      </div>
      <p className="muted">
        Copy details from the original posting. Nothing will be submitted.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          void submit({
            company: data.get("company"),
            title: data.get("title"),
            source_url: data.get("source_url"),
            location: data.get("location"),
            remote: data.get("remote") === "on",
            description: data.get("description"),
            required_skills: split(data.get("required_skills")),
            graduation_years: split(data.get("graduation_years")).map(Number),
            accepted_degrees: split(data.get("accepted_degrees")),
            min_experience_years: number(data.get("min_experience_years")),
            work_country: data.get("work_country"),
            deadline: data.get("deadline")
              ? new Date(String(data.get("deadline"))).toISOString()
              : null,
            requirements_reviewed: data.get("requirements_reviewed") === "on",
          });
        }}
      >
        <div className="form-grid">
          <Field title="Company">
            <input name="company" required maxLength={160} autoFocus />
          </Field>
          <Field title="Role title">
            <input name="title" required maxLength={200} />
          </Field>
        </div>
        <Field title="Posting URL">
          <input
            name="source_url"
            type="url"
            required
            maxLength={2048}
            placeholder="https://company.com/careers/role"
          />
        </Field>
        <div className="form-grid">
          <Field title="Job location">
            <input name="location" maxLength={160} />
          </Field>
          <Field title="Application deadline">
            <input name="deadline" type="datetime-local" />
          </Field>
        </div>
        <label className="checkbox">
          <input type="checkbox" name="remote" />
          This role supports remote work
        </label>
        <Field title="Description">
          <textarea name="description" maxLength={30000} rows={3} />
        </Field>
        <Field
          title="Required skills"
          hint="Comma-separated, as stated in the posting"
        >
          <input name="required_skills" />
        </Field>
        <details>
          <summary>Eligibility requirements</summary>
          <div className="form-grid">
            <Field title="Allowed graduation years">
              <input name="graduation_years" placeholder="2026, 2027" />
            </Field>
            <Field title="Accepted degrees">
              <input name="accepted_degrees" placeholder="BTech, BSc" />
            </Field>
            <Field title="Minimum years of experience">
              <input
                name="min_experience_years"
                type="number"
                min={0}
                max={60}
                step="0.1"
              />
            </Field>
            <Field title="Required work authorization country">
              <input name="work_country" maxLength={100} />
            </Field>
          </div>
        </details>
        <label className="checkbox">
          <input type="checkbox" name="requirements_reviewed" />I checked the
          posting’s requirements. Blank eligibility fields mean no stated
          restriction.
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={close}
          >
            Cancel
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Adding…" : "Add opportunity"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
