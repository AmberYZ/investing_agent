# LLM setup for theme extraction (MVP)

The app can use a **simple API-key–based LLM** for extracting themes and narratives from PDFs—no Vertex AI required. Set `LLM_API_KEY` in `.env` and optionally choose provider and model.

## Quick start

1. Add to `.env`:
   ```bash
   LLM_API_KEY=your-api-key-here
   LLM_PROVIDER=openai
   LLM_MODEL=gpt-4o-mini
   ```
   **For Gemini:** use `LLM_PROVIDER=gemini` and `LLM_MODEL=gemini-1.5-flash` (or `gemini-1.5-pro`).
2. Restart the backend and worker. New ingest jobs will use the LLM for extraction instead of the heuristic fallback.

## Why are no themes showing?

1. **Worker running?** The worker must be running (e.g. `./dev.sh` or `python -m app.worker`) to process queued jobs. If it’s not running, jobs stay "queued" and no themes are extracted.
2. **Correct provider for your key?** For a **Gemini** API key, set `LLM_PROVIDER=gemini`. For OpenAI, use `LLM_PROVIDER=openai`. Using a Gemini key with `openai` (or vice versa) will fail.
3. **Heuristic forced?** If `USE_HEURISTIC_EXTRACTION=true`, the LLM is never called; set it to `false` to use your API key.
4. **Check failures:** Open **Admin → Ingest failures** to see if any jobs failed and the error message.
5. **Backend log:** Set `LOG_FILE=backend/logs/backend.log` in `.env`, restart, then run `tail -f backend/logs/backend.log` to see worker progress (which extraction path was used, theme count, and any errors).

## 503 / RetryError: "Timeout of 600.0s exceeded" or "failed to connect to all addresses"

This usually means the app cannot reach Google’s servers (Vertex AI or Gemini):

- **Firewall or VPN** blocking or timing out connections to `*.googleapis.com` / Google IPs.
- **Corporate or campus network** restricting outbound gRPC/HTTPS to Google.
- **Vertex AI** uses gRPC and can retry for ~600s; connection failures often show as 503 or "Operation timed out (60)".

**What to do:**

1. **Fail faster:** The app now wraps Vertex and Gemini calls in `LLM_TIMEOUT_SECONDS` (default 180). You’ll get a clear timeout error instead of waiting 600s. Set a lower value (e.g. 60) to fail very fast while debugging.
2. **Use Gemini API key instead of Vertex:** If you’re on a locked-down network, the **Gemini API** (REST) may work where **Vertex** (gRPC) does not. Set `LLM_API_KEY` and `LLM_PROVIDER=gemini`, and leave `ENABLE_VERTEX=false`. No Vertex or GCP project needed for extraction.
3. **Try another network:** e.g. mobile hotspot or home connection to see if the issue is network-specific.
4. **Disable Vertex embeddings:** If you only need theme extraction, keep `ENABLE_VERTEX=false` and use `LLM_API_KEY` for extraction; embeddings will be skipped and ingestion will still work.

## Using a VPN

When you’re on a VPN, API calls can fail (timeouts, 503, “failed to connect”) if the VPN blocks or mis-routes traffic to Google/OpenAI. Use this setup so Gemini or OpenAI work reliably.

### Consumer VPN (e.g. QuickQ, NordVPN, ExpressVPN) on macOS

These VPNs **don’t use an HTTP proxy** – they just route your traffic. You **do not** need to set `HTTPS_PROXY` or `HTTP_PROXY` in `.env`.

- Use **Gemini API key** or **OpenAI** (set `LLM_API_KEY`, `LLM_PROVIDER=gemini` or `openai`, `ENABLE_VERTEX=false`). REST works better through consumer VPNs than Vertex/gRPC.
- If you get timeouts or 503: try a **different VPN server** (e.g. a US location) – some regions throttle or block API traffic.
- Optional: **Split tunneling** (if QuickQ supports it) so only the apps you choose use the VPN; you can leave the terminal/backend outside the VPN so API traffic goes direct.

No proxy configuration needed for QuickQ.

**If you still get 503 with QuickQ on:** The app now retries up to 5 times with longer delays (2s, 4s, 8s, …). If it still fails:

1. **Try without VPN** – Turn QuickQ off and run one ingest. If it works, the 503 is VPN-related; try a different QuickQ server (e.g. US) or use split tunneling so the backend skips the VPN.
2. **Switch to OpenAI** – In `.env` set `LLM_PROVIDER=openai`, `LLM_API_KEY=<your OpenAI key>`, `LLM_MODEL=gpt-4o-mini`. OpenAI often works when Gemini returns 503 through the same VPN.
3. **Use a lighter Gemini model** – Set `LLM_MODEL=gemini-1.5-flash` (or `gemini-2.0-flash`) so requests are smaller and less likely to hit capacity limits.

### 1. Prefer API key over Vertex

- **Use the Gemini API (API key), not Vertex.** Set `LLM_PROVIDER=gemini`, `LLM_API_KEY=...`, and `ENABLE_VERTEX=false`. The Gemini API uses plain HTTPS (REST); most VPNs allow it. Vertex uses gRPC and is often blocked or unstable over VPNs.
- **OpenAI** also uses HTTPS and usually works through VPNs with no extra config.

### 2. If your VPN uses an HTTP(S) proxy

Some corporate VPNs require traffic to go through a proxy. Add these to your **repo root `.env`** (the backend and worker load `.env` into the process at startup so proxy vars are applied):

```bash
# In .env (adjust host:port to your VPN/company proxy)
HTTPS_PROXY=http://proxy.company.com:8080
HTTP_PROXY=http://proxy.company.com:8080

# If the proxy must not be used for local/private hosts:
# NO_PROXY=localhost,127.0.0.1
```

Then start the backend/worker as usual (e.g. `./dev.sh` or `python -m app.worker`). The OpenAI and Gemini (REST) clients will use `HTTPS_PROXY` / `HTTP_PROXY` automatically. **Vertex AI (gRPC)** often does not honor these; stick to the Gemini API key when on a proxy VPN.

**How to find your proxy host and port**

- **Many VPNs don’t use a proxy** – they just route traffic. If Gemini or OpenAI work with the VPN on (e.g. the curl checks in §3 succeed), you don’t need `HTTPS_PROXY` at all.
- **macOS (System Settings):**  
  **System Settings → Network → Wi‑Fi (or your interface) → Details → Proxies.**  
  If “Web Proxy (HTTP)” or “Secure Web Proxy (HTTPS)” is enabled, the server and port are shown there (e.g. `proxy.company.com` and `8080`). Use that same host and port in `.env` as `http://host:port`.
- **Windows:**  
  **Settings → Network & Internet → Proxy** (or **Internet Options → Connections → LAN settings**). Note the “Address” and “Port” of the proxy.
- **From the terminal:**  
  If your shell already uses a proxy, it may be in the environment:
  ```bash
  echo $HTTPS_PROXY
  echo $HTTP_PROXY
  ```
  If those print something like `http://proxy.example.com:8080`, use the same value in `.env`.
- **Ask IT / VPN docs:**  
  For work or campus VPNs, the proxy host/port (if any) is often in the VPN setup guide or internal wiki.
- **If you’re not sure:**  
  Try **without** setting `HTTPS_PROXY` first. Use **Gemini API key** (not Vertex) with the VPN on and run the connectivity check (§3). If that works, you don’t need a proxy.

### 3. Quick connectivity check

With the VPN (and proxy, if any) enabled, test that the API is reachable:

```bash
# Gemini (Google)
curl -s -o /dev/null -w "%{http_code}" "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_GEMINI_KEY"

# OpenAI
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer YOUR_OPENAI_KEY" https://api.openai.com/v1/models
```

A `200` (or `401` for wrong key) means the network path works; timeouts or connection errors mean the VPN/proxy is still blocking.

### 4. Optional: split tunneling or try without VPN

- **Split tunneling:** If your VPN supports it, exclude `api.openai.com` and `generativelanguage.googleapis.com` so that traffic goes directly (no VPN). Then you don’t need a proxy.
- **Test without VPN:** Run once with the VPN disabled to confirm the app works; then re-enable VPN and add proxy (step 2) if required.

## Recommended providers

| Provider | Best for | Cost | Notes |
|----------|----------|------|--------|
| **OpenAI** (`openai`) | Reliability, quality | $$$ | `gpt-4o-mini` is cheap and good; `gpt-4o` for best quality. |
| **Gemini** (`gemini`) | Free tier / low cost | Free tier available | Use [Google AI Studio](https://aistudio.google.com/) API key (not Vertex). Set `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-1.5-flash` or `gemini-1.5-pro`. |
| **DeepSeek** (`openai` + base URL) | Cheaper alternative | $ | OpenAI-compatible. Set `LLM_BASE_URL=https://api.deepseek.com`, `LLM_MODEL=deepseek-chat`, `LLM_API_KEY=<DeepSeek key>`. |
| **Qwen** (e.g. DashScope) | Cheaper / regional | $ | Use OpenAI-compatible endpoint if available; set `LLM_BASE_URL` and `LLM_MODEL` accordingly. |

## Configuration

| Env var | Description | Default |
|---------|-------------|---------|
| `LLM_API_KEY` | Your API key. If unset, theme extraction uses the heuristic (no LLM). | (empty) |
| `LLM_PROVIDER` | `openai` (or `openai_compatible`) or `gemini` | `openai` |
| `LLM_MODEL` | Model name (e.g. `gpt-4o-mini`, `gemini-1.5-flash`, `deepseek-chat`) | `gpt-4o-mini` |
| `LLM_BASE_URL` | Optional. For OpenAI-compatible APIs (DeepSeek, Qwen, etc.), set the base URL. | (empty) |
| `LLM_TIMEOUT_SECONDS` | Request timeout in seconds. Gemini can be slow on long documents; increase (e.g. 300) if you see timeouts. | 180 |

### Examples

**OpenAI (ChatGPT)**  
```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

**Gemini (Google AI Studio)**  
```bash
LLM_PROVIDER=gemini
LLM_API_KEY=...
LLM_MODEL=gemini-1.5-flash
```

**DeepSeek**  
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=...
LLM_MODEL=deepseek-chat
```

## Editable prompt

The extraction prompt is user-editable so you can iterate on instructions without code changes:

- **UI:** Admin → Settings (or `/admin/settings`): edit the prompt and save.
- **API:** `GET /settings/extraction-prompt`, `PUT /settings/extraction-prompt` (body: `{ "prompt_template": "..." }`).
- **File:** Backend reads from `backend/app/prompts/extract_themes.txt` if present; otherwise uses `extract_themes_default.txt`. Use placeholders `{{schema}}` and `{{text}}`.

## Disclosure stripping

Before sending text to the LLM, the pipeline strips common disclosure/disclaimer sections (e.g. “Disclosure”, “Risk factors”, “Forward-looking statements”) to save tokens and reduce noise. See `backend/app/extract/disclosure_trim.py`.

## Self-hosted / local models

For a fully local or self-hosted setup:

- Run an **OpenAI-compatible** server (e.g. [Ollama](https://ollama.dev/) with `ollama serve`, or [vLLM](https://docs.vllm.ai/), [OpenAI-compatible LiteLLM](https://docs.litellm.ai/)).
- Set `LLM_BASE_URL=http://localhost:11434/v1` (Ollama) or your server URL, and `LLM_MODEL=your-model-name`.
- You can use smaller distilled models (e.g. Phi, Mistral, Llama) for lower cost; quality may vary for structured extraction.

No code changes are needed as long as the server speaks the OpenAI chat completions API.
