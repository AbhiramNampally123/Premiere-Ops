---
name: Grafana Gemini runtime compatibility
description: Durable runtime constraints for the Grafana MCP and Gemini integration.
---

Grafana Cloud's hosted MCP endpoint uses OAuth and is not interchangeable with a
Grafana stack's HTTP API URL. For service-account-token authentication, launch
the official Grafana MCP server over stdio with `GRAFANA_URL` and
`GRAFANA_SERVICE_ACCOUNT_TOKEN`.

**Why:** A Grafana Cloud base URL returns HTML, the hosted MCP route requires
OAuth, and direct API-token requests to that route are rejected. The official
stdio server works with service-account tokens and still provides MCP tool
discovery.

**How to apply:** Keep the application transport configurable. For stdio,
forward only the runtime environment needed by the MCP subprocess and continue
filtering mutation tools before exposing tools to Gemini. New Gemini models may
reject the legacy `tool` conversation role for function responses; use a
supported user/model conversation role.