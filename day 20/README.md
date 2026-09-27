# Day 20 — Orchestration MCP (mail + Singularity)

Два MCP-сервера в одном агенте: **m365-mail** (stdio) и **SingularityApp** (remote HTTP или stdio REST fallback). Агент сам выбирает инструменты и ведёт длинный флоу «поиск в почте → задача в Singularity».

## Servers

| Id | Transport | Source |
|----|-----------|--------|
| `m365` | stdio | `MCP/mcp/m365-mail` |
| `singularity` | **native** (default): ModumUpCloud `singularity-mcp-server`; else HTTP remote; else thin REST stdio proxy | `run-mcp.sh` / remote URL / `src/singularity_stdio_server.js` |

Tool names are prefixed: `m365__…`, `singularity__…` (native includes `singularity__createTask`).

## Setup

1. API token: Singularity account → **API Access** (env: `SINGULARITY_ACCESS_TOKEN`, alias `SINGULARITY_TOKEN`).
2. Copy env and fill keys:

```bash
cd "ai-challenge/day 20"
cp .env.example .env
# set OPENAI_*, M365_*, SINGULARITY_ACCESS_TOKEN
npm install
npm start   # http://127.0.0.1:5019
```

Transport preference:

```
SINGULARITY_TRANSPORT=native  # ModumUpCloud MCP (default in .env)
SINGULARITY_TRANSPORT=auto    # native → http → stdio proxy
SINGULARITY_TRANSPORT=http    # official remote MCP only
SINGULARITY_TRANSPORT=stdio   # day20 REST proxy only
```

## UI

- Status: both servers + tool counts
- Preset: mail search → create `[Day20]` task
- Trace: ordered `server / tool` steps

## Smoke

```bash
npm run smoke
```

Expects ≥1 `m365` and ≥1 `singularity` tool call in one agent turn.

## Cursor

Workspace [`.cursor/mcp.json`](../../.cursor/mcp.json) includes `singularity` URL for Cursor OAuth UI (separate from this Node agent). Day 20 agent uses `SINGULARITY_TOKEN` from `.env`.

See [example.md](./example.md).
