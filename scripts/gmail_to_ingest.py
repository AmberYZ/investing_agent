#!/usr/bin/env python3
"""
Gmail → Ingest bridge: read emails from a Gmail label and POST to POST /ingest-text.

Usage:
  1. Put Gmail API OAuth credentials at scripts/credentials.json (see GMAIL_SETUP.md).
  2. Set API_BASE_URL in .env or environment (default: http://127.0.0.1:8000).
  3. Run: python scripts/gmail_to_ingest.py
  4. First run opens a browser to sign in with Google; token is saved to scripts/token.json.
  5. Run on a schedule (cron) or manually to process new emails in the label.

Environment:
  API_BASE_URL   - Backend base URL (default http://127.0.0.1:8000).
  GMAIL_LABEL    - Gmail label name(s) to watch, comma-separated for multiple (default: Invest_Digest).
  GMAIL_CREDENTIALS_PATH - Path to credentials.json (default: script_dir/credentials.json).
  GMAIL_TOKEN_PATH      - Path to token.json (default: script_dir/token.json).
  GMAIL_STATE_PATH      - Path to state file for processed message IDs (default: script_dir/.gmail_ingest_state).
  GMAIL_API_TIMEOUT     - Timeout in seconds for Gmail API calls (default: 120). Use a higher value if using VPN.
  HTTPS_PROXY / HTTP_PROXY - Optional proxy URL (e.g. http://proxy:8080) if your network requires it.
  GMAIL_SYNC_HEADLESS   - When 1, script exits instead of opening browser if token expired (used by API daily sync).
"""

from __future__ import annotations

import base64
import os
import socket
import sys
from datetime import date
from pathlib import Path

# Load repo root .env if present
_repo_root = Path(__file__).resolve().parent.parent
_env = _repo_root / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and v and v.startswith('"') and v.endswith('"'):
                    v = v[1:-1].replace('\\"', '"')
                if k and v and v.startswith("'") and v.endswith("'"):
                    v = v[1:-1].replace("\\'", "'")
                os.environ.setdefault(k, v)

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Install dependencies: pip install -r scripts/requirements-gmail.txt", file=sys.stderr)
    sys.exit(1)

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp

# Scope lockdown: read-only. Allows reading messages only; cannot send or delete email.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Max number of message IDs to keep in state (avoid huge file)
MAX_STATE_IDS = 2000


def _get_proxy_info():
    """Build ProxyInfo from HTTPS_PROXY or HTTP_PROXY so Gmail API (HTTPS) uses the proxy."""
    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if not proxy_url or not proxy_url.strip():
        return None
    return httplib2.proxy_info_from_url(proxy_url.strip(), method="https")


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _get_credentials():
    script_dir = _script_dir()
    creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH") or str(script_dir / "credentials.json")
    token_path = os.environ.get("GMAIL_TOKEN_PATH") or str(script_dir / "token.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                print(
                    f"Missing {creds_path}. Download OAuth credentials from Google Cloud Console and save as credentials.json. See GMAIL_SETUP.md.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if os.environ.get("GMAIL_SYNC_HEADLESS") == "1":
                print(
                    "Gmail token missing or expired and GMAIL_SYNC_HEADLESS=1 (running from API). "
                    "Run 'python scripts/gmail_to_ingest.py' once manually to sign in and save a new token.",
                    file=sys.stderr,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def _decode_body(data: dict | None) -> str:
    if not data or "data" not in data:
        return ""
    raw = data["data"]
    pad = 4 - len(raw) % 4
    if pad != 4:
        raw += "=" * pad
    return base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")


def _get_message_body(payload: dict) -> tuple[str, str]:
    """Return (body_text, content_type) where content_type is 'text/html' or 'text/plain'."""
    html_parts: list[str] = []
    plain_parts: list[str] = []

    def collect(p: dict) -> None:
        if p.get("body", {}).get("data"):
            ct = (p.get("mimeType") or "text/plain").lower()
            body = _decode_body(p["body"])
            if body:
                if "html" in ct:
                    html_parts.append(body)
                else:
                    plain_parts.append(body)
        for part in p.get("parts") or []:
            if part.get("filename"):
                continue
            if part.get("body", {}).get("data"):
                mime = (part.get("mimeType") or "").lower()
                body = _decode_body(part["body"])
                if body:
                    if "html" in mime:
                        html_parts.append(body)
                    else:
                        plain_parts.append(body)
            elif part.get("parts"):
                collect(part)

    collect(payload)
    html = "\n".join(html_parts).strip()
    plain = "\n".join(plain_parts).strip()
    if html and len(html) > 10:
        return html, "text/html"
    return (plain or html), "text/plain"


def _clean_html_for_ingest(html: str) -> str:
    """Strip navigation/sidebar/boilerplate; keep main content and tables (e.g. Substack)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav"]):
        tag.decompose()
    to_remove = []
    for tag in soup.find_all(True):
        role = (tag.get("role") or "").lower()
        if role == "navigation" or "banner" in role or "contentinfo" in role:
            to_remove.append(tag)
            continue
        cls = " ".join(tag.get("class") or []).lower()
        tid = (tag.get("id") or "").lower()
        for needle in ("nav", "sidebar", "header", "footer", "menu", "banner"):
            if needle in cls or needle in tid:
                to_remove.append(tag)
                break
    for tag in to_remove:
        tag.decompose()
    return str(soup)


def _get_header(msg: dict, name: str) -> str:
    name = name.lower()
    for h in msg.get("payload", {}).get("headers") or []:
        if (h.get("name") or "").lower() == name:
            return (h.get("value") or "").strip()
    return ""


def _resolve_label_ids(service, label_names: list[str]) -> list[str]:
    """Resolve label names to Gmail API label IDs. Case-insensitive."""
    label_names = [n.strip() for n in label_names if (n or "").strip()]
    if not label_names:
        print("GMAIL_LABEL is empty. Set it to one or more label names, comma-separated (e.g. Invest_Digest).", file=sys.stderr)
        raise SystemExit(1)
    try:
        response = service.users().labels().list(userId="me").execute()
    except (socket.timeout, OSError) as e:
        print("Failed to list Gmail labels (timeout or network).", file=sys.stderr)
        raise SystemExit(1) from e
    labels = response.get("labels") or []
    name_to_id = {(lab.get("name") or "").lower(): lab["id"] for lab in labels}
    ids: list[str] = []
    missing: list[str] = []
    for name in label_names:
        want = name.lower()
        if want in name_to_id:
            ids.append(name_to_id[want])
        else:
            missing.append(name)
    if missing:
        sample = list(name_to_id.keys())[:15]
        print(
            f'Gmail label(s) not found: {missing}. '
            f"Available (sample): {sample}. Set GMAIL_LABEL to one or more names, comma-separated.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return ids


def load_state(state_path: str) -> tuple[str | None, set[str]]:
    """Load last_synced date (YYYY/MM/DD) and set of processed message IDs."""
    last_synced: str | None = None
    ids: set[str] = set()
    if not os.path.exists(state_path):
        return None, ids
    with open(state_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("last_synced="):
                last_synced = line.split("=", 1)[1].strip()
            else:
                ids.add(line)
    return last_synced, ids


def save_state(state_path: str, last_synced: str, ids: set[str]) -> None:
    """Save last_synced date and processed IDs for incremental sync."""
    lst = list(ids)
    if len(lst) > MAX_STATE_IDS:
        lst = lst[-MAX_STATE_IDS:]
    with open(state_path, "w") as f:
        f.write(f"last_synced={last_synced}\n")
        for i in lst:
            f.write(i + "\n")


def main() -> None:
    api_base = (os.environ.get("API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    label_env = os.environ.get("GMAIL_LABEL") or "Invest_Digest"
    label_names = [n.strip() for n in label_env.split(",") if n.strip()]
    script_dir = _script_dir()
    state_path = os.environ.get("GMAIL_STATE_PATH") or str(script_dir / ".gmail_ingest_state")

    creds = _get_credentials()
    timeout_secs = int(os.environ.get("GMAIL_API_TIMEOUT", "120"))
    proxy_info = _get_proxy_info()
    if proxy_info:
        print("Using proxy from HTTPS_PROXY/HTTP_PROXY", file=sys.stderr)
    http = httplib2.Http(timeout=timeout_secs, proxy_info=proxy_info)
    authorized_http = AuthorizedHttp(creds, http=http)
    service = build("gmail", "v1", http=authorized_http)

    label_ids = _resolve_label_ids(service, label_names)
    label_id_to_name = dict(zip(label_ids, label_names))
    last_synced, processed = load_state(state_path)
    all_message_ids: set[str] = set()
    list_kw_base: dict = {"userId": "me", "maxResults": 100}
    if last_synced:
        list_kw_base["q"] = f"after:{last_synced}"
    try:
        for label_id in label_ids:
            list_kw = {**list_kw_base, "labelIds": [label_id]}
            result = service.users().messages().list(**list_kw).execute()
            for m in result.get("messages") or []:
                all_message_ids.add(m["id"])
    except (socket.timeout, OSError) as e:
        print(
            "Connection to Gmail API failed (timeout or network error). "
            "Check your internet connection, VPN, and firewall/proxy settings.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    messages = [{"id": mid} for mid in all_message_ids]
    new_count = 0
    had_failure = False
    for m in messages:
        mid = m["id"]
        if mid in processed:
            continue
        try:
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
            payload = full.get("payload") or {}
            body_str, content_type = _get_message_body(payload)
            if not body_str:
                processed.add(mid)
                continue
            if content_type == "text/html":
                body_str = _clean_html_for_ingest(body_str)
            subject = _get_header(full, "Subject") or "(No subject)"
            date_hdr = _get_header(full, "Date")
            published_at = None
            if date_hdr:
                try:
                    from email.utils import parsedate_to_datetime
                    published_at = parsedate_to_datetime(date_hdr).isoformat()
                except Exception:
                    pass
            message_label_ids = set(full.get("labelIds") or [])
            matched_labels = [label_id_to_name[lid] for lid in message_label_ids if lid in label_id_to_name]
            source_name = "gmail · " + ", ".join(matched_labels) if matched_labels else "gmail"
            r = requests.post(
                f"{api_base}/ingest-text",
                json={
                    "content": body_str,
                    "content_type": content_type,
                    "title": subject[:500],
                    "published_at": published_at,
                    "source_name": source_name,
                },
                timeout=60,
            )
            if r.status_code in (200, 201):
                new_count += 1
                processed.add(mid)
                print(f"Ingested: {subject[:60]}...")
            else:
                had_failure = True
                print(f"HTTP {r.status_code} for {subject[:40]}: {r.text[:200]}", file=sys.stderr)
        except Exception as e:
            had_failure = True
            print(f"Error processing message {mid}: {e}", file=sys.stderr)
            if "Connection refused" in str(e) or "127.0.0.1" in str(e):
                print(
                    "Backend API not reachable. Start the API (e.g. uvicorn app.main:app --port 8000) and re-run.",
                    file=sys.stderr,
                )

    today = date.today().strftime("%Y/%m/%d")
    # Only advance last_synced when no failures, so next run will retry failed messages (same date range).
    next_synced = (last_synced if had_failure and last_synced else today)
    save_state(state_path, next_synced, processed)
    if new_count:
        print(f"Done. Ingested {new_count} new message(s).")
    else:
        print("Done. No new messages to ingest.")


if __name__ == "__main__":
    main()
