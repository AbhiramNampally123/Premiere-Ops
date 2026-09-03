# CPU Doctor Agent

Grafana observability agent that queries live Grafana data through MCP and uses Gemini to analyze it; local `/proc` diagnostics remain available as a secondary script.

## Run & Operate

- `python3 main.py` — run the primary Grafana MCP + Gemini agent
- `python3 main.py --question "Is CPU utilization elevated?"` — ask one Grafana question
- `python3 cpu_doctor_agent.py` — run the secondary local-only health scan
- `python3 cpu_doctor_agent.py --json` — emit a machine-readable local report
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
- `main.py` — project entrypoint for the Grafana/Gemini path
- `README.md` — usage and automation notes
- `grafana_gemini_agent/` — standalone Grafana MCP + Gemini read-only CLI
- `artifacts/api-server` — shared API server scaffold

## Architecture decisions

- The primary agent uses the official Python MCP and Google Gemini SDKs.
- Linux `/proc` is treated as the source of truth for CPU, memory, uptime, and process metrics.
- Missing or transient procfs values are reported as unavailable instead of being replaced with guessed data.
- Grafana questions use only MCP tools discovered as read/query operations; mutation tools are excluded before Gemini sees them.

## Product

The agent produces a one-shot health report with thresholds, actionable findings, and an exit code suitable for shell automation.

The Grafana Gemini Agent is the primary Python application. Configure
`GRAFANA_MCP_URL` (or the stdio transport variables) and run `python3 main.py`;
its test suite uses fakes and does not require live credentials.

## User preferences

_None recorded._

## Gotchas

- The diagnostics script targets Linux and depends on `/proc`; it is not intended for native macOS or Windows execution without a platform adapter.
- The Grafana MCP URL must be configured before the primary agent can connect; it does not silently fall back to local data.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
