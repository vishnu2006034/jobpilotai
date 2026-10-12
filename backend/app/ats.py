"""Bounded GET-only adapters for documented public ATS endpoints."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
import time

import httpx
from pydantic import ValidationError

from .jobs import JobInput
from .operations import TaskFailure

MAX_BYTES = 32 * 1024 * 1024
MAX_POSTINGS = 5000
MAX_PAGES = 25
PAGE_SIZE = 200
MAX_SECONDS = 90
HOSTS = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/",
         "lever": "https://api.lever.co/v0/postings/", "lever_eu": "https://api.eu.lever.co/v0/postings/"}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def plain(value):
    if not isinstance(value, str):
        raise TaskFailure("invalid_feed")
    parser = PlainText()
    parser.feed(unescape(unescape(value)))
    return re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts)).strip()[:30000]


@dataclass(frozen=True)
class FeedItem:
    external_id: str
    url: str
    data: dict


def retry_seconds(value):
    if not value:
        return 0
    try:
        return max(0, min(int(value), 86400))
    except ValueError:
        try:
            return max(0, min(int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()), 86400))
        except (ValueError, TypeError):
            return 0


def normalize(provider, company, raw):
    try:
        external_id = str(raw["id"])
        if not external_id or len(external_id) > 150 or not isinstance(raw["id"], (str, int)) or isinstance(raw["id"], bool):
            raise ValueError("Bad external ID")
        if provider == "greenhouse":
            description = plain(raw.get("content", ""))
            location = raw.get("location", {}).get("name", "")
            title, url, workplace = raw["title"], raw["absolute_url"], "unspecified"
            salary = None
        else:
            sections = [raw.get("descriptionPlain") or plain(raw.get("description", ""))]
            for section in raw.get("lists", []):
                sections.append(str(section.get("text", "")) + "\n" + plain(section.get("content", "")))
            sections.append(raw.get("additionalPlain") or plain(raw.get("additional", "")))
            description = "\n\n".join(sections)[:30000]
            location = raw.get("categories", {}).get("location", "")
            title, url = raw["text"], raw["hostedUrl"]
            workplace = raw.get("workplaceType", "unspecified")
            if workplace not in {"unspecified", "on-site", "hybrid", "remote"}:
                workplace = "unspecified"
            salary = raw.get("salaryRange")
            if salary is not None:
                if not isinstance(salary, dict):
                    raise ValueError("Invalid salary")
                salary = {key: salary.get(key) for key in ("currency", "interval", "min", "max")}
                for key in ("min", "max"):
                    value = salary[key]
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                        raise ValueError("Invalid salary")
                if salary["min"] is not None and salary["max"] is not None and salary["min"] > salary["max"]:
                    raise ValueError("Invalid salary range")
        validated = JobInput(company=company, title=title, source_url=url, location=location or "",
                             description=description, remote=workplace == "remote", requirements_reviewed=False)
        data = validated.model_dump(mode="json", exclude={"source_url"})
        data.update(workplace_type=workplace, salary=salary)
        return FeedItem(external_id, str(validated.source_url), data)
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        raise TaskFailure("invalid_feed") from None


def fetch_feed(provider, board, company, client=None):
    if provider not in HOSTS or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", board):
        raise TaskFailure("invalid_source")
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(15, connect=10), follow_redirects=False,
                                    headers={"User-Agent": "JobPilot/0.2 public-job-discovery", "Accept": "application/json"})
    started, total_bytes = time.monotonic(), 0
    items, seen = [], set()

    def read(url, params):
        nonlocal total_bytes
        with client.stream("GET", url, params=params) as response:
            if response.status_code == 429:
                raise TaskFailure("rate_limited", True, retry_seconds(response.headers.get("retry-after")))
            if response.status_code >= 500:
                raise TaskFailure("provider_unavailable", True)
            if response.status_code == 404:
                raise TaskFailure("board_not_found")
            if response.status_code != 200:
                raise TaskFailure("provider_rejected")
            content = bytearray()
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_BYTES:
                    raise TaskFailure("feed_too_large")
                if time.monotonic() - started > MAX_SECONDS:
                    raise TaskFailure("fetch_time_limit", True)
                content.extend(chunk)
            try:
                return json.loads(content)
            except (ValueError, UnicodeDecodeError):
                raise TaskFailure("invalid_feed") from None

    try:
        for page in range(MAX_PAGES):
            if provider == "greenhouse":
                body = read(HOSTS[provider] + board + "/jobs", {"content": "true"})
                if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
                    raise TaskFailure("invalid_feed")
                rows = body["jobs"]
                meta = body.get("meta")
                if not isinstance(meta, dict) or meta.get("total") != len(rows):
                    raise TaskFailure("incomplete_feed")
            else:
                rows = read(HOSTS[provider] + board, {"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE})
                if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                    raise TaskFailure("invalid_feed")
            for raw in rows:
                item = normalize(provider, company, raw)
                if item.external_id in seen:
                    raise TaskFailure("duplicate_feed_identity", True)
                seen.add(item.external_id)
                items.append(item)
                if len(items) > MAX_POSTINGS:
                    raise TaskFailure("feed_too_large")
            if provider == "greenhouse" or len(rows) < PAGE_SIZE:
                return items
        raise TaskFailure("page_limit")
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
        raise TaskFailure("network_error", True) from None
    finally:
        if own_client:
            client.close()
