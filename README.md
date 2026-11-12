# TwinAI

**A passive background agent that turns an engineer's everyday work into a queryable "digital twin" of their knowledge.**

> This repository is a project write-up. TwinAI was built with a team of four at an internal company hackathon (2026), and the source code is not public.

## The problem

Engineering knowledge lives in people's heads. When the one person who knows how a system works is on leave, in another time zone, or has left the company, everyone else is blocked. Wikis help, but only for what someone took the time to write down.

## The idea

Instead of asking engineers to document, TwinAI watches how they already work (with explicit consent), distils that activity into a structured knowledge base, and lets teammates ask questions that are answered from it, with citations, even when the expert is offline.

## How it works

```
Capture  →  Daemon pipeline  →  Knowledge base  →  Query engine  →  Surfaces
```

1. **Capture (opt-in, per source):** IDE extension, terminal hook, browser extension, pull-request webhooks, LLM chat history, chat messages, and calendar.
2. **Daemon (FastAPI, runs locally on login):**
   - sanitizer that redacts secrets and personal data before anything is stored
   - session aggregation and normalization
   - two-layer dedup: hashed Bloom filter at the event level plus a semantic diff at the knowledge level
   - LLM "wiki ingest" that updates topic pages with source citations
3. **Knowledge base (Git-versioned, user-owned):**
   - one Markdown page per domain, plus a profile and a co-occurrence knowledge graph
   - an append-only raw event log
   - auto-committed every 15 minutes
   - rolls up from personal to team to org level
4. **Query engine:**
   - BM25 domain match, then knowledge-graph traversal, then LLM synthesis
   - confidence score from source quality, recency, expertise, and corroboration
   - low-confidence questions are not answered; they are logged as knowledge gaps
5. **Routing:** a question can be routed to the teammate whose twin knows the topic best, weighted by expertise and availability.
6. **Surfaces:** web dashboard (Next.js), IDE chat commands, and a team chat bot.

## Privacy by design

- Nothing is captured until the user gives consent, and every source can be turned off individually.
- Secrets, tokens, and personal identifiers are scrubbed before storage.
- HR and payroll sites are blocked at the browser-extension level.
- Each user owns their knowledge-base repository; other people get read-only access.
- Every answer the twin gives is logged for the owner to audit, and uninstalling removes everything locally.

## My contribution

Platform architecture, the capture daemon and ingestion pipeline, the knowledge engine (knowledge-base layout, graph, and query flow), and the LLM-assistant skill integration.

## Tech

Python · FastAPI · BM25 (`rank-bm25`) · FAISS · GitPython · Next.js · VS Code / IntelliJ extensions · Chrome MV3 extension

## Outcome

TwinAI was built from scratch during the hackathon, and the team now uses it day to day.
