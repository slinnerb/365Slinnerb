# Password-protecting Ollama + exposing it to your friend

This sets up: a **password** on your AI, **encryption** so the password isn't sent
in plain text, an **endpoint allow-list** so even a leaked password can only chat
(not pull or delete your models), and a **port forward** so your friend can reach it.

There are 3 steps:
- **Step 1 (on the server):** paste the prompt below into the Claude running on
  10.0.0.54. It installs a reverse proxy (Caddy) and locks Ollama down.
- **Step 2 (your router):** forward one port to the server.
- **Step 3 (the app):** put the URL + password into Settings — on both your PC and
  your friend's.

---

## Step 1 — Paste this to the Claude on your server (10.0.0.54)

> Copy everything in the box and send it to the Claude running on the server.

```
I'm running Ollama on this Windows machine (LAN IP 10.0.0.54) with the model
qwen2.5:7b. I want to safely expose it to one friend over the internet. Ollama
has no built-in auth, so please put Caddy in front of it as a reverse proxy.
Requirements:

1. Install Caddy (https://caddyserver.com) if it isn't already installed.

2. Lock Ollama so it only listens on localhost (127.0.0.1:11434) and is NOT
   directly reachable from the LAN or internet. On Windows that means setting the
   system environment variable OLLAMA_HOST=127.0.0.1:11434 and restarting Ollama.
   (Remove any previous OLLAMA_HOST=0.0.0.0 setting.)

3. Generate a long random secret token (32+ chars, URL-safe, no spaces) and show
   it to me clearly at the end — I need to type it into an app. Call it THE_TOKEN.

4. Configure Caddy to listen on port 11435 with these rules, in this order:
   - Use a self-signed TLS cert (Caddy's `tls internal`) so traffic is encrypted.
   - Reject any request that does NOT have the header
     `Authorization: Bearer THE_TOKEN` with HTTP 401.
   - Reject any request whose path is NOT one of /api/chat, /api/tags,
     /api/generate with HTTP 403 (this blocks model pull/delete/create/push even
     if the token leaks).
   - For allowed + authorized requests, reverse_proxy to 127.0.0.1:11434 and set
     the upstream Host header to "localhost" (Ollama requires this).
   - Make sure streaming responses (NDJSON from /api/chat) are not buffered.

5. Open the Windows Firewall for inbound TCP on port 11435, scoped to the Private
   profile (and Public only if my router's forwarded traffic arrives that way).

6. Start Caddy as a background service so it survives reboots.

7. Verify it works and show me the test results:
   - A request to https://localhost:11435/api/tags WITHOUT the token returns 401.
   - A request WITH the token returns the model list (use curl -k for the
     self-signed cert).
   - A request to https://localhost:11435/api/pull WITH the token returns 403.

At the end, print clearly: THE_TOKEN value, the port (11435), and confirmation
that Ollama is now localhost-only.
```

When the server Claude finishes, **write down the token it shows you.**

---

## Step 2 — Forward a port on your router

Your friend reaches your server through your home router. You need to forward the
Caddy port to the server.

1. Find your router's admin page (usually `http://192.168.1.1` or `http://10.0.0.1`
   — check the sticker on the router). Log in.
2. Find **Port Forwarding** (sometimes under "Advanced", "NAT", or "Virtual Server").
3. Add a rule:
   - **External / public port:** `11435`
   - **Internal IP:** `10.0.0.54`  (your server)
   - **Internal port:** `11435`
   - **Protocol:** TCP
4. Save / apply.
5. **Forward ONLY port 11435.** Do not forward 11434 — that would expose Ollama
   directly and bypass the password.

**Find your public IP:** on the server, open <https://whatismyipaddress.com> — the
IPv4 number is your public address (looks like `73.x.x.x`). Your friend will use
that.

> ⚠️ **Heads up — your home IP can change.** Most home internet has a *dynamic* IP
> that changes every so often. If the app suddenly can't connect weeks later, your
> IP probably changed — re-check whatismyipaddress and update the friend's URL. If
> this gets annoying, set up free Dynamic DNS (e.g. duckdns.org) and use that
> hostname instead of the raw IP.

---

## Step 3 — Put the URL + password into the app's Settings

Do this on **your friend's PC** (and on your own, since Ollama is now localhost-only
and your old `http://10.0.0.54:11434` setting will no longer work):

1. Open the app → **Settings**.
2. **Server URL:** `https://YOUR_PUBLIC_IP:11435`
   (on your own PC at home you can instead use `https://10.0.0.54:11435`)
3. **Model:** `qwen2.5:7b`
4. **Password:** paste THE_TOKEN from Step 1.
5. **Uncheck** "Verify HTTPS certificate" — required because Caddy uses a
   self-signed cert. (Traffic is still encrypted; this just skips the
   name-match check.)
6. Click **Test AI connection** → should go green ("OK. Models available: …").
7. Click **Save**, then open **Ask AI**.

---

## What this protects against

- **Internet scanners** that probe for open Ollama servers → blocked (they don't
  have the password; they get 401).
- **A leaked password** → limited to chatting only; your models can't be pulled,
  deleted, or replaced (403 on those endpoints).
- **Eavesdropping** of the password in transit → mitigated by TLS encryption.

## What it does NOT do

- The self-signed cert means there's no protection against a determined
  man-in-the-middle who can intercept *and* actively tamper with traffic (rare for
  a hobby setup, but real). If you want airtight encryption with a trusted cert and
  no port forwarding at all, the Cloudflare Tunnel option in AI_REMOTE_ACCESS.md is
  stronger — tell Claude and we can switch to it.
