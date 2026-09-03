---
name: MCP HTTP transport compatibility
description: Compatibility constraint for Python MCP streamable HTTP clients.
---

The Python MCP streamable HTTP transport has changed its connection API across
releases: older clients accept request headers directly, while current clients
take an externally-created `httpx2.AsyncClient`.

**Why:** The project must support the current official client while remaining
usable with Grafana MCP deployments pinned to an older compatible client.

**How to apply:** Detect the transport callable's supported keyword at runtime.
When using an injected client, pass headers and timeouts through `httpx2` and
register that client in the same async exit stack as the MCP transport.