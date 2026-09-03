# Grafana Gemini Agent

This standalone Python CLI answers natural-language questions about live Grafana
metrics. It discovers read/query tools from a configured Grafana MCP server,
lets Gemini request bounded follow-up reads, and answers only from the returned
observations. It never creates, edits, or deletes Grafana state.

## Install

From the repository root, install the isolated application's dependencies:

```bash
python3 -m pip install -r grafana_gemini_agent/requirements.txt
```

Python 3.11 or newer is required. The official `mcp` Python client and Google's
`google-genai` SDK are the only runtime dependencies.

## Configure

Set these environment variables. Keep credentials in your shell environment or
secret manager; the CLI never prints their values.

| Variable | Required | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | yes | Google Gemini API credential |
| `GRAFANA_MCP_TRANSPORT` | yes | `streamable-http` (default), `sse`, or `stdio` |
| `GRAFANA_MCP_URL` | HTTP/SSE | Grafana MCP endpoint, such as `https://grafana.example.com/api/mcp` |
| `GRAFANA_MCP_COMMAND` | stdio | MCP server executable; passed directly, never through a shell |
| `GRAFANA_MCP_ARGS_JSON` | no | JSON string array of stdio arguments; default `[]` |
| `GRAFANA_MCP_HEADERS_JSON` | no | JSON string object of HTTP headers; default `{}` |
| `GEMINI_MODEL` | no | Gemini model; default `gemini-2.5-flash` |
| `GRAFANA_MCP_TIMEOUT_SECONDS` | no | Per-session/discovery/tool timeout, 1–120; default `20` |
| `GEMINI_TIMEOUT_SECONDS` | no | Per-model-request timeout, 1–180; default `45` |
| `GRAFANA_MAX_TOOL_ROUNDS` | no | Maximum Gemini follow-up rounds, 1–8; default `4` |
| `GRAFANA_MAX_RESPONSE_BYTES` | no | Maximum serialized MCP observation size, 1,024–2,000,000; default `100000` |

For a Grafana MCP server that needs authentication, put the required header in
`GRAFANA_MCP_HEADERS_JSON`. If the token is already in `GRAFANA_TOKEN`, a
double-quoted shell value expands it without printing it:

```bash
export GRAFANA_MCP_HEADERS_JSON="{\"Authorization\":\"Bearer ${GRAFANA_TOKEN}\"}"
```

Prefer constructing that value from a secret manager rather than putting a token
in shell history. URLs with embedded usernames or passwords are rejected.

The `streamable-http` transport is the recommended setting for current Grafana
MCP servers. `sse` is available for servers that expose the older SSE transport.
Use `stdio` only when you run a local MCP server command.

## Run

One-shot question:

```bash
GEMINI_API_KEY="$GEMINI_API_KEY" \
GRAFANA_MCP_TRANSPORT=streamable-http \
GRAFANA_MCP_URL="https://grafana.example.com/api/mcp" \
python3 -m grafana_gemini_agent --question "What is the p95 request latency for the checkout service over the last hour?"
```

Interactive prompt:

```bash
python3 -m grafana_gemini_agent
```

Use `quit` or `Ctrl-D` to leave the prompt. `Ctrl-C` exits cleanly with status
130. Normal output contains the answer and the names of consulted tools, not raw
MCP payloads.

## Supported questions and safety

Questions should require read-only Grafana metric or observability data, such as
current error rate, CPU utilization over a time window, request latency, or a
comparison between services. At discovery time the agent rejects tools whose
names or descriptions indicate mutations and only exposes tools with an
explicit read/query/metric-oriented signal. Tool schemas are discovered at
runtime; no Grafana tool names are hardcoded.

The MCP session, each read, each Gemini request, the response size, and the
number of follow-up rounds are bounded. Empty or malformed observations are
passed to Gemini as missing data so the answer can state uncertainty. Connection,
authentication, malformed-protocol, timeout, unsupported-tool, invalid-call,
and model failures produce actionable errors without echoing endpoint headers or
API credentials.

## Test

The tests use fake MCP and Gemini clients and do not need credentials, a live
Grafana instance, or network access:

```bash
python3 -m unittest discover -s grafana_gemini_agent/tests -v
```

The package can also be installed with its local `pyproject.toml` if a console
script is preferred:

```bash
python3 -m pip install ./grafana_gemini_agent
grafana-gemini-agent --question "Is the API error rate elevated?"
```