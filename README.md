# CPU Doctor Agent

CPU Doctor Agent is a Grafana observability agent powered by Gemini. It queries
live Grafana data through MCP, then uses Gemini to explain the observations in
plain English. A separate dependency-free local diagnostics script is also
included for offline machine checks.

## Run it

Configure the Grafana MCP endpoint and run the primary agent:

```bash
export GRAFANA_MCP_TRANSPORT=streamable-http
export GRAFANA_MCP_URL="https://your-grafana.example.com/api/mcp"
python3 main.py --question "Is CPU utilization elevated over the last hour?"
```

`GEMINI_API_KEY` is read from the Replit Secret with that name. The agent
discovers Grafana's available tools at runtime and only exposes read/query
tools to Gemini.

For a local-only machine snapshot, run the secondary script:

```bash
python3 cpu_doctor_agent.py
```

The scan reports:

- Aggregate CPU usage over a short sample
- 1-minute load and load per CPU
- Memory pressure and available memory
- Host uptime
- Processes using the most CPU during the sample
- Actionable healthy, warning, or critical findings

## Automation

Use the Grafana agent interactively:

```bash
python3 main.py
```

The local script also supports JSON for monitoring:

```bash
python3 cpu_doctor_agent.py --json --interval 1 --top 10
```

The command exits with:

- `0` when no issue is detected
- `1` when a warning threshold is reached
- `2` when a critical threshold is reached

The script currently targets Linux because it relies on `/proc`. If a
`/proc` metric is unavailable, the report says `unavailable` rather than
silently inventing a value.

## Grafana Gemini Agent

The `grafana_gemini_agent/` package is the primary application path. It uses
the official Python MCP client to connect to Grafana over Streamable HTTP, SSE,
or stdio, and the official Google Gemini SDK for analysis. It never creates,
edits, or deletes Grafana state.

See [`grafana_gemini_agent/README.md`](grafana_gemini_agent/README.md) for
installation, environment variables, transport setup, examples, and the
credential-free test command. The existing CPU Doctor script is unchanged.