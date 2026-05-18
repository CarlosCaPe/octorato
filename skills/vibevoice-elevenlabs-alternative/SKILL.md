---
name: vibevoice-elevenlabs-alternative
description: Microsoft's open-source voice synthesis model — local, real-time-capable text-to-speech that can replace ElevenLabs for non-streaming, on-device, or cost-sensitive use cases. MIT licensed. Use when a client needs voice generation without sending audio prompts to a third-party API, when ElevenLabs per-minute costs are eating margin, or when the brain's `speech` skill needs a fully-local alternative for regulated / air-gapped engagements.
---

# VibeVoice — Microsoft's Open-Source Voice Synthesis

Open-source TTS from Microsoft Research — generates voice locally, no per-minute API costs, no data sent to a third party. Complements (not replaces) the brain's existing `speech` skill which uses the OpenAI Audio API.

## When to use

- Client needs voice generation but cannot send transcripts to OpenAI / ElevenLabs (regulated, PHI, IP-sensitive)
- ElevenLabs per-minute pricing is hurting unit economics on a high-volume use case
- Want zero-API-cost voice for prototypes, demos, internal tooling
- Need offline / air-gapped voice synthesis
- Pair with the brain's `transcribe` skill for full local STT + TTS loops (transcribe handles audio → text, VibeVoice handles text → audio)

## When NOT to use

- Need the absolute best voice quality currently available — ElevenLabs is still ahead on naturalism for many languages
- Low-latency streaming voice in a live agent loop — verify VibeVoice's streaming support before promising
- Voice cloning of a specific person — quality / licensing depends; check current docs
- Production deliverable where the client needs Microsoft-level commercial support — it's an OSS research project, not a hosted SaaS

## Source of truth

- Repository: `github.com/microsoft/VibeVoice` (verify current URL — Microsoft hosts many OSS projects)
- License: MIT (verify against current state)
- Org: Microsoft Research
- Self-hosted: yes, run locally (GPU recommended for real-time)

## VibeVoice vs ElevenLabs vs the brain's `speech` skill

| Scenario | Recommended |
|---|---|
| Production app, best voice quality, willing to pay | ElevenLabs |
| OpenAI-managed voices via existing API key | brain's `speech` skill (existing) |
| Regulated industry, no third-party data flow | **VibeVoice** |
| Bulk generation where cost is the constraint | **VibeVoice** |
| Air-gapped / on-prem deployment | **VibeVoice** |
| Voice cloning of arbitrary speakers | Verify each tool's current capability + license |
| Real-time streaming in a live agent loop | Check VibeVoice streaming support before deciding |

## Quick start (rough — verify against current README)

```bash
# Clone the repo
git clone https://github.com/microsoft/VibeVoice
cd VibeVoice

# Follow the install instructions — typically a Python env + model weights download
# Run inference locally (CLI or Python API)
```

GPU is strongly recommended for real-time use; CPU is fine for batch / offline generation.

## Recommendation pattern (proposals)

> "For client engagements where voice output is needed but ElevenLabs cost or data residency is a blocker, recommend VibeVoice as the self-hosted alternative. Quality is good enough for most internal-tool, prototype, and accessibility use cases, and it pairs cleanly with our existing `transcribe` skill for full local STT + TTS loops. Keep ElevenLabs in the rec stack for premium-quality, hosted-fine use cases."

## Limits to disclose to a client

- **Quality gap**: ElevenLabs is still the quality leader in 2026 for many languages; VibeVoice is "good enough" for many use cases, not "best in class"
- **Compute**: realtime requires GPU; CPU is batch-only
- **No vendor SLA**: it's an OSS research project, not a commercial service
- **Language coverage**: verify the languages the client needs are supported at the quality bar required

## Related brain assets

- `speech` — existing skill, OpenAI Audio API; VibeVoice is the local alternative
- `transcribe` — existing skill, STT side of the loop; pairs with VibeVoice for end-to-end local audio
- `sora` — when video + voice are needed together
- AI Engineer agent — for evaluating local model deployment + GPU sizing for a specific arm
