"""Conservative discovery hints; never an eligibility or compensation guarantee."""
import re

POLICY_VERSION = "chennai-remote-bengaluru8-v1"
POLICY_DESCRIPTION = "SDE/data analysis; fresher or 2027 signals; Chennai on-site, India-compatible remote, Bengaluru with posted minimum INR 8 LPA."


def target_posting(data):
    title = data["title"].lower()
    content = data.get("description", "").lower()
    location = data.get("location", "").lower()
    workplace = data.get("workplace_type", "unspecified")
    reasons, review = [], []

    def result(status):
        return {"status": status, "reasons": reasons + review, "policy_version": POLICY_VERSION}

    if re.search(r"\b(senior|sr\.?|staff|principal|manager|director|lead|architect)\b", title):
        reasons.append("Title indicates a senior/leadership role")
        return result("excluded")
    if re.search(r"\b(sde|software engineer|software developer|developer|data analyst|data analytics|analytics analyst|(?:back[ -]?end|front[ -]?end|full[ -]?stack|mobile)(?: / api)? engineer)\b", title):
        reasons.append("Title contains a software-development or data-analysis role signal")
    else:
        reasons.append("Title does not contain a target role signal")
        return result("excluded")
    early = re.search(r"\b(fresher[s]?|new grad(?:uate)?s?|graduate[s]?|entry[ -]level|early career|2027)\b", title + " " + content)
    if early:
        reasons.append(f"Early-career/batch text signal: {early.group(0)} (verify exact eligibility)")
    else:
        review.append("Fresher/2027 eligibility is not stated clearly")

    remote_signal = workplace == "remote" or "remote" in location or re.search(r"\bremote\b", title)
    if remote_signal:
        if re.search(r"\b(india|worldwide|anywhere|global)\b", location):
            reasons.append("Remote posting includes India or an unrestricted global-location signal")
        elif re.search(r"\b(united states|usa|us only|canada|united kingdom|uk only|europe|emea|australia)\b", location):
            reasons.append("Remote posting names a region outside India")
            return result("excluded")
        else:
            review.append("Confirm this remote role can be performed from India")
    elif "chennai" in location:
        if workplace == "hybrid":
            review.append("Chennai role is hybrid; confirm whether it suits your on-site preference")
        else:
            reasons.append("Chennai location; verify on-site arrangements with the employer")
    elif "bengaluru" in location or "bangalore" in location:
        salary = data.get("salary") or {}
        if str(salary.get("currency", "")).upper() == "INR" and str(salary.get("interval", "")).lower() in {"per-year", "year", "yearly", "annual"}:
            minimum, maximum = salary.get("min"), salary.get("max")
            if minimum is not None and minimum >= 800000:
                reasons.append("Bengaluru: structured posted minimum is at least INR 8 LPA")
            elif maximum is not None and maximum < 800000:
                reasons.append("Bengaluru: posted salary range is below INR 8 LPA")
                return result("excluded")
            else:
                review.append("Bengaluru salary minimum is not confirmed at INR 8 LPA or above")
        else:
            review.append("Bengaluru needs confirmed INR annual salary of at least 8 LPA; no salary is assumed")
    elif not location or location.strip() == "india":
        review.append("Confirm Chennai, eligible remote work, or Bengaluru with INR 8+ LPA")
    else:
        reasons.append("Location is outside the requested shortlist")
        return result("excluded")
    return result("needs_review" if review else "potential_match")
