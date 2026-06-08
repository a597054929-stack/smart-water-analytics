# Architecture Decision Records (ADR)

This directory contains the project's ADRs — short documents that capture
**why** a significant technical choice was made, not just **what** was chosen.

## Format

Each ADR follows MADR (Markdown Architectural Decision Records):

1. **Title** — one-line summary
2. **Status** — Accepted / Deprecated / Superseded
3. **Date** — when decided
4. **Context** — the problem and options considered
5. **Decision** — what was chosen
6. **Consequences** — positive/negative outcomes + mitigations
7. **References** — code, files, related docs

## Index

| #   | Title                                              | Status   | Date       |
| --- | -------------------------------------------------- | -------- | ---------- |
| 001 | [使用 SQLite 而非 PostgreSQL](0001-使用-sqlite-不-postgres.md) | Accepted | 2026-06-07 |
| 002 | [用 Pandera 在管道邊界做 Schema 校驗](0002-pandera-做-schema-校驗.md) | Accepted | 2026-06-07 |
| 003 | [單一 monorepo 包含四大組件](0003-monorepo-單倉多組件.md) | Accepted | 2026-06-07 |
| 004 | [Claude Code 設計哲學對我們項目的啟發](0004-claude-code-design.md) | Accepted | 2026-06-08 |

## How to add a new ADR

1. Copy `template.md` (or one of the existing ADRs)
2. Number sequentially: `NNNN-kebab-case-title.md`
3. Update this index
4. Open a PR — review focuses on the trade-off section

## References

- [MADR](https://adr.github.io/madr/) — the template we follow
- [Michael Nygard's original ADR concept](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
