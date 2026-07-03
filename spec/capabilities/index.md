# Capabilities Index

---

## What Is a Capability?

A capability is a single, discrete action or behavior the agent performs.

## Capabilities in This Project

| Capability | File | Phase(s) |
|-----------|------|----------|
| Dataset Ingestion | [dataset-ingestion.md](dataset-ingestion.md) | 1 (upload/clean/profile single file), 2 (library), 3a (derived/exported datasets) |
| Conversational Analysis | [conversational-analysis.md](conversational-analysis.md) | 1 (single-call), 2 (adaptive depth + cross-file + follow-ups), 3a (charts/tables/exports), 3b (anomaly flags) |
| Library & Sessions | [library-and-sessions.md](library-and-sessions.md) | 2 (full) |
| Audit & Cost Tracking | [audit-and-cost-tracking.md](audit-and-cost-tracking.md) | 1 (backend writes only), 3b (audit-history UI), 3c (cost UI + streaming) |

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer sub-agent will:
1. Create a new file in this directory (`<name>.md`, no number prefix)
2. Update this index
3. Flag any dependencies on existing capabilities
4. Self-review that it fits the architecture and data model before returning

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Business rules**
- **Success criteria** (how we test it)
