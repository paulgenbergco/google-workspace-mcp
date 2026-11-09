# Remote mode: use this server from claude.ai

`python server.py --http` serves the same 110 tools over Streamable HTTP, behind OAuth, so it can be added to claude.ai as a **custom connector**. A connector added on claude.ai works in claude.ai chat, Cowork, and cloud Claude Code sessions. The stdio mode used by Claude Desktop and local Claude Code is unchanged.

## How it fits together

```
claude.ai ──HTTPS──> tunnel (Tailscale Funnel) ──> 127.0.0.1:8765  server.py --http
                                                     │
              sign-in: "Sign in with Google" ────────┤  only remote.allowed_emails get a token
              Google APIs: credentials/tokens/*.json ┘  (same per-account tokens as stdio mode)
```

- **claude.ai is the OAuth client; this server is the authorization server.** claude.ai registers itself automatically (dynamic client registration), then sends you to Google to sign in. The server checks the Google identity against `allowed_emails` and only then issues a token. There are no passwords to manage.
- **Sign-in uses a second Google OAuth client, a "Web application" one.** It asks only for `openid email`, and it is separate from `credentials/client_secret.json`, the Desktop client that holds the Gmail/Drive grants.
- **Registration is locked to claude.ai's callback** (plus loopback, for local Claude Code). Without that lock, anyone could register a client pointing at their own site, send you a crafted link, and collect a token the moment your browser auto-completes the Google login. The account chooser is also forced on every sign-in.
- **Local paths are disabled.** `save_path`, `source_path` and `attachments` name files on the server's disk, so a prompt-injected email could otherwise read that disk and mail its contents out. In remote mode those arguments are removed from the schemas and refused if sent. Binary downloads (`gmail_download_attachment`, `drive_read_content`, `drive_export`) come back as MCP image content (PNG/JPEG/GIF/WebP) or an embedded blob resource, up to 10 MB.
- **State** (registered clients, plus hashed access and refresh tokens) lives in `credentials/remote_state.json`, mode 0600. Access tokens last 1 hour. Refresh tokens last 30 days and rotate on every use. If you delete the file, claude.ai just asks you to reconnect.

## Setup (Clawdette, macOS)

Do steps 1 to 4 on Clawdette. Steps 5 and 6 are in a browser.

### 1. Code and dependencies

Clawdette already has a checkout at `~/Dev/google-workspace-mcp`. Leave it alone and make a **separate clone** next to it, so the remote server can be pulled and restarted without touching whatever runs from the existing one (the banks daemon).

```bash
cd ~/Dev && git clone https://github.com/paulgenbergco/google-workspace-mcp.git google-workspace-mcp-remote
cd ~/Dev/google-workspace-mcp-remote
bash setup.sh                       # venv + deps (now includes uvicorn)
```

### 2. Accounts and tokens

Copy them from the existing checkout first, then fill any gaps.

```bash
cd ~/Dev/google-workspace-mcp-remote
cp ../google-workspace-mcp/config.json .
cp ../google-workspace-mcp/credentials/client_secret.json credentials/
cp ../google-workspace-mcp/credentials/tokens/*.json credentials/tokens/
.venv/bin/python -c "import json;print(list(json.load(open('config.json'))['accounts']))"
ls credentials/tokens
```

Every account you want on claude.ai needs a `config.json` entry **and** a token file. For any that are missing (for example the laptop's `genberg`, `alai`, `lvlon`, `cloe`), add the entry to `config.json` and run `.venv/bin/python setup_auth.py` here. It opens a browser on Clawdette and only prompts for accounts without a token. Copying the token files from the laptop's `credentials/tokens/` also works, as long as both machines use the same `client_secret.json`.

### 3. Public HTTPS with Tailscale Funnel

```bash
tailscale funnel --bg 8765          # macOS app: /Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --bg 8765
tailscale funnel status             # prints https://<machine>.<tailnet>.ts.net
```

The first run may print a link to turn on Funnel and HTTPS for the tailnet. Approve it, then rerun. Write down the `https://...ts.net` URL. It is your **public URL** in the steps below.

If you'd rather use your own domain through Cloudflare Tunnel (for example `mcp.genberg.co`), that works too. Point the tunnel at `http://127.0.0.1:8765` and use that hostname as the public URL.

### 4. Google sign-in client

1. Open [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) in the **same project** as `client_secret.json`.
2. Click **+ Create credentials → OAuth client ID → Web application**. Name it `MCP remote sign-in`.
3. Under **Authorized redirect URIs**, add `<public URL>/oauth/google/callback`.
4. Click Create, then **Download JSON**, and save it on Clawdette as `credentials/remote_client_secret.json`.

### 5. Configure and start

Add a `remote` block to `config.json`:

```json
"remote": {
  "public_url": "https://<machine>.<tailnet>.ts.net",
  "allowed_emails": ["paul@genberg.co"],
  "port": 8765
}
```

```bash
bash deploy/install-launchd.sh                                # starts now and at every login, restarts on crash
curl -s http://127.0.0.1:8765/healthz                         # {"ok":true}
curl -s https://<public URL>/.well-known/oauth-protected-resource/mcp   # JSON, from the outside
tail -f ~/Library/Logs/gworkspace-mcp/server.log
```

### 6. Add the connector on claude.ai

1. Go to [claude.ai → Settings → Connectors](https://claude.ai/customize/connectors) and click **Add custom connector**.
2. Name: `Google Workspace`. URL: `<public URL>/mcp`. Leave the advanced OAuth client ID and secret **empty**.
3. Click **Connect**, pick `paul@genberg.co` in Google's chooser, and you land back on claude.ai.
4. Start a **new** cloud Claude Code session and ask it to run `list_accounts` with `verify: true`.

On a Team or Enterprise plan, an owner may first need to allow custom connectors in organization settings.

## Operations

| Task | Command |
|---|---|
| Restart after `git pull` | `bash deploy/install-launchd.sh` |
| Stop and remove | `bash deploy/install-launchd.sh uninstall` |
| Logs | `tail -f ~/Library/Logs/gworkspace-mcp/server.log` |
| Revoke every claude.ai session | Stop the server, delete `credentials/remote_state.json`, start it again |
| Remove a person's access | Take their address out of `allowed_emails` and restart. Their existing tokens stop working immediately |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `STARTUP ERROR` in the log | The message names the missing piece: the `remote` block, the client file, or a non-https `public_url` |
| Google says `redirect_uri_mismatch` | The redirect URI on the Web client must exactly equal `<public URL>/oauth/google/callback` |
| claude.ai shows `invalid_redirect_uri` on connect | claude.ai changed its callback URL. The log line `refused client registration with redirect_uris [...]` shows the new one. Add it to `remote.allowed_redirect_uris` (this replaces the default list, so keep the old entries) |
| claude.ai shows "not allowed on this server" | You picked a Google account that isn't in `allowed_emails` |
| A tool says an account is not authenticated | Its token is missing, revoked, or expired. If the OAuth consent screen is External + Testing, Google expires refresh tokens after 7 days, which an always-on server will hit. Publish the app or make it Internal |
| Connector worked, then stopped overnight | The Mac slept, or Funnel is off. Check `tailscale funnel status` and System Settings → Energy |
