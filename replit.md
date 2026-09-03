# CPU Doctor Agent

Dependency-free Linux diagnostics that inspect CPU pressure, load, memory, uptime, and top processes.

## Run & Operate

- `python3 cpu_doctor_agent.py` — run a human-readable health scan
- `python3 cpu_doctor_agent.py --json` — emit a machine-readable report
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `cpu_doctor_agent.py` — the runnable diagnostics agent
- `README.md` — usage and automation notes
- `artifacts/api-server` — shared API server scaffold

## Architecture decisions

- The first version uses Python's standard library only, so it can run immediately without dependency installation.
- Linux `/proc` is treated as the source of truth for CPU, memory, uptime, and process metrics.
- Missing or transient procfs values are reported as unavailable instead of being replaced with guessed data.

## Product

The agent produces a one-shot health report with thresholds, actionable findings, and an exit code suitable for shell automation.

## User preferences

_None recorded._

## Gotchas

- The diagnostics script targets Linux and depends on `/proc`; it is not intended for native macOS or Windows execution without a platform adapter.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
