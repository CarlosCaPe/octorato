---
name: whatsapp-mcp-bridge-gotchas
description: "Hard-won fixes for standing up the lharries/whatsapp-mcp bridge (whatsmeow + WhatsApp Web multidevice), encrypted, with send as a reversible dial. Covers the 403 media-download root cause (direct path stripped of its CDN auth query), the 405 client-outdated fix (bump whatsmeow + add context.Context to changed APIs), QR-vs-phone-code pairing, encrypt-at-rest without sudo (gocryptfs static binary), read-only vs send-enabled enforcement, and liveness/identity/verification gotchas (bridge freshness probe, @lid JID migration, outgoing REST sends absent from messages.db). Load before installing or debugging a personal WhatsApp MCP."
metadata:
  type: reference
---

# WhatsApp MCP bridge (lharries/whatsmeow) gotchas

Lived 2026-06-10 standing up `lharries/whatsapp-mcp` for a personal number, read-only and encrypted. The repo works but ships against a pinned whatsmeow that WhatsApp now rejects, and its media download is broken in a subtle way. The fixes below are the root causes, not workarounds.

## 1. 403 on media download (the big one). Root cause: stripped CDN auth
**Symptom:** `/api/download` returns `download failed with status code 403` for every image/audio/doc, including a message received live (so it is NOT URL expiry).

**Root cause:** the bridge stores the full media `url` and reconstructs the direct path with `extractDirectPathFromURL`, which **strips the query string** (`?ccb=...&oh=...&oe=...&_nc_sid=...`). Those query params are the **CDN auth tokens**. whatsmeow's `Download` builds the download URL as `mediaHost + directPath`, so a path without its query is unauthenticated and the CDN returns 403.

**Fix (one line):** in `extractDirectPathFromURL`, keep the query. Return `"/" + parts[1]` WITHOUT the `strings.SplitN(pathPart, "?", 2)[0]` strip. This recovers history-synced media too (no need to re-forward the message), because the stored URL already carries valid tokens.

## 2. 405 "Client outdated" on connect. Bump whatsmeow + add context
**Symptom:** bridge connects then `Client outdated (405) connect failure (client version: ...)`, websocket closes.

**Fix:** the pinned whatsmeow is stale. `go get go.mau.fi/whatsmeow@latest && go get go.mau.fi/util@latest && go mod tidy`, rebuild. The current whatsmeow API added a `context.Context` first arg to several calls the bridge uses; add `context.Background()` to: `client.Download`, `client.GetGroupInfo`, `client.Store.Contacts.GetContact`, `sqlstore.New`, `container.GetFirstDevice`. Build errors point to each line.

## 3. Pairing: prefer the phone code over the QR
The terminal QR (qrterminal half-block) is often unscannable from a chat surface and rotates every ~20s, so it times out. **Phone-number pairing is far more reliable.** whatsmeow supports `client.PairPhone(ctx, phone, true, whatsmeow.PairClientChrome, "Chrome (Linux)")`, which returns an 8-char code the operator types in WhatsApp > Linked Devices > Link with phone number. Patch the QR loop to call it when an env like `WA_PAIR_PHONE=<intl digits>` is set. The bridge links as its own device; the operator's WhatsApp Web in a browser stays logged in (multidevice allows several).

## 4. Encrypt at rest without sudo
`gocryptfs` built from source needs `libssl-dev` (sudo). Skip that: download the **prebuilt static binary** from the gocryptfs GitHub releases (`*_linux-static_amd64.tar.gz`), it has no deps and FUSE is usually present (`/dev/fuse` + `fusermount`). Init a cipher dir, mount it, and `ln -s <mount> whatsapp-bridge/store` so the bridge writes messages.db + the whatsmeow session encrypted. Passphrase via `-passfile` from a 600 file or, better, the SO keyring (`secret-tool`).

## 5. Send enforcement is a dial, not a fact (read-only vs send-enabled)
Read-only is a DEPLOYMENT DECISION with two layers, both reversible:
1. **Tool registration in the server source** (`main.py`): the send functions (`send_message`, `send_file`, `send_audio_message`) live in `whatsapp.py` and the bridge exposes `/api/send` regardless. Removing their `@mcp.tool()` registration hides them from the MCP schema; re-adding it restores them. The capability never left the stack.
2. **Harness deny** in `settings.json` `permissions.deny`: `mcp__whatsapp__send_*`. Note: an agent cannot remove its own deny rules (the auto-mode classifier blocks self-widening of permissions, and it also blocks tunneling the send through curl while the deny stands). Flipping this layer is an operator-only step, by design.

Gotcha that costs a whole exchange: a skill doc that says "read-only by design" describes the decision AT WRITE TIME, not the current system. Before declaring "no se puede enviar", grep the live code (`grep "def send" whatsapp.py`, `grep "api/send" main.go`). If the operator asks for the capability, the answer is to flip the dial at the root (re-register tools + operator removes deny), never to build workarounds around your own lock.

## 6. Operational
The Go bridge must stay alive (whatsmeow keeps the multidevice session); run it as a `systemd --user` service with `loginctl enable-linger`. The gocryptfs mount must be remounted on boot too. Both are prerequisites for the MCP server to read.

## 7. Liveness, identity, and verification gotchas (post-mortem tested)
1. **"The MCP answers" is NOT "the bridge is alive."** The python MCP server only reads the DB; the Go bridge is what syncs. The real liveness probe is data freshness: `SELECT MAX(timestamp) FROM messages` vs now. If it lags hours, the bridge is down even though every MCP query "works". On reconnect with a live session, WhatsApp re-delivers the queued backlog in minutes, no re-pairing needed (check `whatsapp.db` mtime to guess session health before assuming re-pair).
2. **Contacts migrate to `@lid` JIDs.** A person's chat under `<phone>@s.whatsapp.net` can freeze in time while their new messages land under `<numeric>@lid`. Searching only the phone JID yields a false "no new messages". Sweep by content/media across all chats, or match the @lid chat by conversation context, before claiming silence.
3. **Outgoing sends via `/api/send` are NOT persisted to `messages.db`** (only event-handler traffic is stored). A DB read-back after sending returns empty; that is a storage gap, not a delivery failure. The delivery evidence is the bridge log line `Message sent true ...` (whatsmeow ack). Verify sends against the log, and final-verify visually on a phone/WhatsApp Web.

Related: [[mcp-stack-setup]], [[phi-aware-rag-ingestion]] (sensitive-data ingestion), [[sops-age-git-encryption]].
