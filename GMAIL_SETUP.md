# Gmail → Ingest setup (Substack and other emails)

This guide gets emails from a Gmail label into your investing agent via the local script (no Zapier/Make). After setup, run the script on a schedule or manually.

---

## 1. Gmail label

1. In Gmail, go to **Settings** (gear) → **See all settings** → **Filters and Blocked Addresses**.
2. Click **Create a new filter**.
3. In **From**, enter: `@substack.com` (or specific senders).
4. Click **Create filter**.
5. Check **Apply the label** → choose **New label** → name it `Invest_Digest` (or any name you like).
6. Click **Create filter**.

You’ll use this label name in the script (default is `Invest_Digest`).

---

## 2. Google Cloud: enable Gmail API and create OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick an existing one):
   - Top bar: click the project name → **New Project** → e.g. `Investing Agent` → **Create**.
3. Enable the Gmail API:
   - **APIs & Services** → **Library** → search **Gmail API** → open it → **Enable**.
4. Configure the OAuth consent screen (required before creating credentials):
   - **APIs & Services** → **OAuth consent screen**.
   - Choose **External** (unless you use a Google Workspace org) → **Create**.
   - App name: e.g. `Investing Agent Gmail Bridge`. Set **User support email** and **Developer contact**. **Save and Continue**.
   - **Scopes**: **Add or Remove Scopes** → add `https://www.googleapis.com/auth/gmail.readonly` → **Update** → **Save and Continue**.
   - **Test users**: add your Gmail address so you can sign in during testing → **Save and Continue**.
5. Create OAuth client credentials:
   - **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**.
   - Application type: **Desktop app**.
   - Name: e.g. `Gmail bridge`.
   - **Create**.
6. Download the client configuration:
   - In the list, open your new **OAuth 2.0 Client ID**.
   - Click **Download JSON**.
   - Save the file as `credentials.json` in the **`scripts`** folder of this repo:
     ```
     Investing agent/
       scripts/
         credentials.json   <-- put it here
         gmail_to_ingest.py
     ```
   - Rename the file to `credentials.json` if the download used a longer name.

You do **not** need to copy any “API key” into the app. The script uses this JSON for the one-time browser sign-in; after that it uses a saved token. The script uses **read-only** Gmail scope (it can read messages but cannot send or delete email).

---

## 3. Install script dependencies and run

From the **repo root**:

```bash
pip install -r scripts/requirements-gmail.txt
```

Optional: set the backend URL and label in your **repo root `.env`** (the script reads it):

```bash
# Already in .env for ingest client; script uses it too
API_BASE_URL=http://127.0.0.1:8000

# Label name from step 1 (default: Invest_Digest). Multiple labels: comma-separated, e.g. Invest_Digest,Newsletter
GMAIL_LABEL=Invest_Digest
```

Make sure your **backend is running** (e.g. `uvicorn` on port 8000). Then:

```bash
python scripts/gmail_to_ingest.py
```

- **First run**: a browser window opens so you can sign in with the Gmail account that has the label. After you approve, the script saves `scripts/token.json` and continues. You won’t be asked again unless the token is removed or revoked.
- **Incremental sync**: The script saves the last run date in the state file. On later runs it only fetches messages **after** that date, so runs stay fast. First run fetches all messages in the label.
- **HTML cleaning**: For Substack (and other HTML) emails, the script strips navigation, sidebars, and boilerplate before sending, keeping main content and tables.
- Processed message IDs are stored in `scripts/.gmail_ingest_state` so the same email is never re-sent. in `scripts/.gmail_ingest_state` so it doesn’t re-send the same email.

---

## 4. Run on a schedule (optional)

To run the script every 10 minutes (macOS/Linux), add a crontab:

```bash
crontab -e
```

Add a line (adjust path and Python if needed):

```
*/10 * * * * cd /Users/you/Desktop/Investing\ agent && /usr/bin/python3 scripts/gmail_to_ingest.py >> scripts/gmail_ingest.log 2>&1
```

Or use a simple loop (for testing):

```bash
while true; do python scripts/gmail_to_ingest.py; sleep 600; done
```

---

## 5. Troubleshooting

- **“Missing credentials.json”**  
  Put the downloaded OAuth JSON in `scripts/credentials.json` as in step 2.

- **“Access blocked” or “App not verified”**  
  You’re using an “External” app in test mode. In the OAuth consent screen, add your Gmail under **Test users**. You can then sign in; no “verification” request needed for personal use.

- **HTTP 503 from /ingest-text**  
  Backend may have ingest paused (`PAUSE_INGEST=true`) or queue full. Check backend logs and `.env`.

- **No new messages ingested**  
  Confirm the label name matches (e.g. `Invest_Digest`). In Gmail, open the label and check that Substack emails are there. The script only processes messages that haven’t been processed before (see `.gmail_ingest_state`).

- **Script fails with import errors**  
  Run `pip install -r scripts/requirements-gmail.txt` from the repo root (or the same environment where you run the script).

- **`socket.timeout: timed out` or connection to Gmail API fails**  
  The script cannot reach Google’s servers.   If you **use a VPN or corporate proxy** to access Gmail:
  - Ensure the VPN is connected before running the script.
  - **Proxy:** In `.env` set `HTTPS_PROXY=http://proxy-host:port` (e.g. `HTTPS_PROXY=http://proxy.company.com:8080`) or `HTTP_PROXY=...`. The script reads these and uses them for Gmail API calls. You should then see `Using proxy from HTTPS_PROXY/HTTP_PROXY` when you run the script.
  - **Timeout:** Set `GMAIL_API_TIMEOUT=180` (or higher) in `.env` if connections are slow.

- **No `.venv` in repo root**  
  The project’s virtualenv may be under `backend/`. From repo root run: `backend/.venv/bin/python scripts/gmail_to_ingest.py`. Or use `python3 scripts/gmail_to_ingest.py` and ensure dependencies are installed for that Python (`pip install -r scripts/requirements-gmail.txt`).
