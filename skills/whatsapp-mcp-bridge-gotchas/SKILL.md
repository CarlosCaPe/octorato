---
name: whatsapp-mcp-bridge-gotchas
description: "Hard-won fixes for standing up the lharries/whatsapp-mcp bridge (whatsmeow + WhatsApp Web multidevice) read-only and encrypted. Covers the 403 media-download root cause (direct path stripped of its CDN auth query), the 405 client-outdated fix (bump whatsmeow + add context.Context to changed APIs), QR-vs-phone-code pairing, encrypt-at-rest without sudo (gocryptfs static binary), and read-only enforcement. Load before installing or debugging a personal WhatsApp MCP."
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

## 5. Read-only enforcement (three layers)
1. **Strip the send tools from the server source** (`main.py`): remove `send_message`, `send_file`, `send_audio_message` so they are absent from the MCP schema. Strongest layer.
2. **Harness deny** in `settings.json` `permissions.deny`: `mcp__whatsapp__send_message`, `mcp__whatsapp__send_file`, `mcp__whatsapp__send_audio_message`.
3. Open the messages DB read-only where the server reads it.

## 6. Operational
The Go bridge must stay alive (whatsmeow keeps the multidevice session); run it as a `systemd --user` service with `loginctl enable-linger`. The gocryptfs mount must be remounted on boot too. Both are prerequisites for the MCP server to read.

Related: [[mcp-stack-setup]], [[phi-aware-rag-ingestion]] (sensitive-data ingestion), [[sops-age-git-encryption]].
