# Giving your friend access to the Ask AI feature

The local Ollama server runs at `http://10.0.0.54:11434` — a private LAN address
your friend can't reach over the internet. To give them access, you need to
bridge their machine to your AI server in a secure way.

**Recommended: Tailscale** (free, 5-minute setup, no public exposure).

> ⚠️ **Important**: Ollama has no built-in authentication. Anyone who can reach
> the API can use the model, pull new ones, or delete models. Don't put it on a
> public URL without an auth layer.

---

## Option 1 — Tailscale (recommended)

Tailscale creates a private encrypted mesh network between machines you trust.
Your friend's app will point at a `100.x.x.x` URL that only works for devices
you've explicitly authorized. No firewall holes, no public exposure.

### Step 1 — Install on the AI server (10.0.0.54)

1. Open <https://tailscale.com/download/windows> on the server.
2. Download and run the installer.
3. When it prompts, sign in (Google / Microsoft / GitHub / email — pick any).
4. Once installed, open Tailscale from the system tray → it will show this
   machine's Tailscale IP (something like `100.x.y.z`). **Write it down.**

### Step 2 — Install on your friend's machine

1. Send your friend the link <https://tailscale.com/download/windows>.
2. They run the installer.
3. **For sign-in, two options:**
   - **Easiest:** they sign in with the same Google/Microsoft/email account
     you used. Same Tailscale "tailnet" → no sharing setup needed.
   - **Better separation:** they sign in with their own account. You then go to
     <https://login.tailscale.com/admin/machines>, click the `...` next to your
     server machine, choose **Share node…**, and paste the share link into a
     message to them. They click it and accept.

### Step 3 — Confirm your friend can reach the server

On the friend's machine, in PowerShell:

```powershell
Invoke-RestMethod http://100.x.y.z:11434/api/tags
```

(replace `100.x.y.z` with the Tailscale IP from Step 1)

If it returns a `models` list, you're done with the network setup.

### Step 4 — Point the MLB app at the Tailscale URL

On the friend's machine, in the MLB app:

1. Click **Settings**.
2. In **Server URL**, replace `http://10.0.0.54:11434` with
   `http://100.x.y.z:11434` (the Tailscale IP from Step 1).
3. Leave **Model** as `qwen2.5:7b`.
4. Click **Test AI connection** — should show **OK. Models available: qwen2.5:7b**.
5. Click **Save**.
6. Click **Ask AI** and try a question.

That's it. The connection is encrypted by Tailscale and only works while both
devices have Tailscale running.

### Optional: also switch your own machine to the Tailscale URL

If you sometimes use the app away from your home LAN (e.g., on a laptop at a
coffee shop), switch your own **Server URL** to the same Tailscale address. It
works on the LAN *and* remotely, so you only need one config.

---

## Option 2 — Cloudflare Tunnel (no install on friend's side)

Use this if you don't want your friend to install Tailscale. The downside is
you're putting Ollama on a public URL — you **must** add an auth layer.

1. Sign up at <https://dash.cloudflare.com> (free).
2. Add a domain (or use a free `*.trycloudflare.com` quick tunnel).
3. Install `cloudflared` on the server: <https://github.com/cloudflare/cloudflared/releases>.
4. Quick test:
   ```
   cloudflared tunnel --url http://localhost:11434
   ```
   This prints a public `https://xxxx.trycloudflare.com` URL. Friend can hit it.
5. **Before sharing publicly**, set up Cloudflare Access (free for ≤50 users) to
   require your friend's email to log in before reaching the tunnel. Otherwise
   anyone on the internet who guesses the URL can use your AI.
6. Friend opens **Settings** → **Server URL** = the tunnel URL → **Save**.

---

## Option 3 — Don't do this (port forwarding)

Opening port 11434 on your router and giving your friend your home IP is
*technically* possible but means **anyone scanning the internet** can find your
Ollama and use/abuse it. Don't.

---

## What if it stops working later?

- **Friend's app shows "AI unavailable"** → check Tailscale is running on both
  machines (system tray icon should be green on both sides).
- **Tailscale IP changed** → it usually doesn't, but if you reinstall, check
  the Tailscale admin panel for the new IP and update the friend's Settings.
- **Model returns "not found"** → run `ollama list` on the server. If `qwen2.5:7b`
  is gone, `ollama pull qwen2.5:7b` to reinstall.
