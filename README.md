# CPU Doctor Agent

CPU Doctor Agent is a dependency-free Linux diagnostic script that gives a
quick health snapshot of a machine. It reads the Linux `/proc` interface
directly, so it does not need `psutil` or any other package.

## Run it

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

Use JSON for monitoring or another agent:

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

The repository also includes an isolated Python CLI for grounded, read-only
questions about live Grafana metrics. It discovers query tools from a Grafana
MCP server and lets Gemini request bounded follow-up reads; it never changes
Grafana state.

See [`grafana_gemini_agent/README.md`](grafana_gemini_agent/README.md) for
installation, environment variables, transport setup, examples, and the
credential-free test command. The existing CPU Doctor script is unchanged.