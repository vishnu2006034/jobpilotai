export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-JobPilot": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "Could not reach JobPilot. Check that the backend is running.",
    );
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = error.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (item: { loc?: string[]; msg?: string }) =>
                  `${item.loc?.slice(1).join(".")}: ${item.msg}`,
              )
              .join("; ")
          : `Request failed (${response.status})`;
    if (response.status === 401)
      window.dispatchEvent(new Event("jobpilot:unauthorized"));
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export type User = { id: string; email: string };
export type Profile = {
  full_name: string;
  graduation_year: number | null;
  degree: string;
  experience_years: number | null;
  location: string;
  skills: string[];
  authorized_countries: string[];
  preferred_roles: string[];
  version: number;
};
export type Job = {
  provenance: string;
  source_details: {
    provider?: string;
    revision?: number;
    retrieved_at?: string;
  };
  id: string;
  company: string;
  title: string;
  source_url: string;
  location: string;
  remote: boolean;
  description: string;
  required_skills: string[];
  graduation_years: number[];
  accepted_degrees: string[];
  min_experience_years: number | null;
  work_country: string;
  deadline: string | null;
  requirements_reviewed: boolean;
  saved: boolean;
  created_at: string;
};
export type Match = {
  job_id: string;
  eligibility: string;
  score: number | null;
  reasons: string[];
  matched_skills: string[];
  skill_gaps: string[];
  stale: boolean;
  profile_version: number;
  scoring_version: string;
  components: Record<string, number | null>;
};
export type Application = {
  id: string;
  job_id: string;
  company: string;
  title: string;
  state: string;
  version: number;
  allowed_transitions: string[];
  updated_at: string;
};
export type TimelineEvent = {
  id: string;
  next_state: string;
  version: number;
  evidence: { note: string };
  created_at: string;
};
export type Page<T> = { items: T[]; next_offset: number | null };
export type Summary = {
  jobs: number;
  saved_jobs: number;
  applications: number;
  by_state: Record<string, number>;
};
