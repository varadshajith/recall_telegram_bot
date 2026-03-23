# Recall v2 — Implementation Plan

**Date:** 2026-03-22
**Version:** v2
**Status:** Draft

---

## Task Roadmap

### Task 1 — Database & Migrations
- [ ] Install alembic
- [ ] Run `alembic init alembic`
- [ ] Configure alembic.ini and env.py with DATABASE_URL
- [ ] Create initial migration from existing models
- [ ] Add User, Session, CollaboratorInvite models
- [ ] Update Prompt model — add tags, embedding, speaker_attribution,
      session_id, user_id, created_at
- [ ] Enable Redis persistence in docker-compose.yml

### Task 2 — Timestamps + Auto-tagging
- [ ] Add created_at to all brief extractions
- [ ] Update LLM system prompt to extract tags alongside
      features/decisions/next_steps/blockers
- [ ] Store tags as JSON column on Prompt

### Task 3 — Memory Layer
- [ ] On each voice note, fetch last 5 briefs for that user
- [ ] Pass as context to LLM: "Previous briefs: ..."
- [ ] Update system prompt to surface connections between ideas

### Task 4 — Smart Context Window
- [ ] On voice note received, check if user has a brief created
      within last 30 minutes
- [ ] If yes — update existing brief instead of creating new
- [ ] If no — create new brief as normal

### Task 5 — Semantic Search
- [ ] Install sentence-transformers
- [ ] Load Nomic Embed Text locally
- [ ] On brief creation, generate embedding and store as JSON
- [ ] Implement /search — embed query, cosine similarity against
      all stored embeddings, return top 3 results

### Task 6 — New Commands
- [ ] /prompt — 2-3 question interactive flow, generate context-aware
      prompt using brief history
- [ ] /brainstorm — pass latest brief to LLM with brainstorm prompt,
      return ideas and pivots
- [ ] /summary — fetch last 7 days, group by tag, generate digest
- [ ] /evolution — fetch all briefs for same project, show timeline
      with dates and key decision points
- [ ] /ideas [tag] — filter briefs by tag, return list

### Task 7 — Collaborators
- [ ] /add @username — create CollaboratorInvite, send Telegram invite
- [ ] Invite accept/decline flow
- [ ] Shared session — both users write to same session
- [ ] Attribution — tag each voice note with sender's username

### Task 8 — Speaker Diarization
- [ ] Install pyannote.audio
- [ ] Run diarization before transcription
- [ ] Split audio by speaker, transcribe each segment
- [ ] Merge with labels: "Speaker A: ..., Speaker B: ..."
- [ ] Link to Telegram usernames when collaborators active

### Task 9 — BotFather Registration
- [ ] Register all commands via /setcommands:
      prompt, brainstorm, summary, search, evolution,
      ideas, challenge, history, add, get

---

## Implementation Order

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9

Do not skip Task 1 — everything else depends on the updated data model.

---

## Verification Checklist

- [ ] Migrations run without losing v1 data
- [ ] Voice note creates brief with timestamp and tags
- [ ] Follow-up within 30 min updates existing brief
- [ ] /search returns semantically relevant results
- [ ] /summary returns grouped weekly digest
- [ ] /add flow works end to end
- [ ] Speaker labels appear in multi-person briefs
- [ ] All commands autofill in Telegram