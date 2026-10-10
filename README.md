# Forge

A durable workflow platform for AI-driven applications, built on
[Temporal](https://temporal.io/). Forge connects messaging channels to
app workers through a gateway. Workers fulfil user intent, send replies,
and manage approval flows. Temporal handles state, retries, and signals.

## Quick start

Prerequisites: Docker and Docker Compose.

```bash
git clone https://github.com/pycaster/forge.git
cd forge
cp .env.example .env
```

Set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in `.env` to point
at any OpenAI-compatible endpoint. Then start the stack:

```bash
make up
```

This starts three services:

| Service | Port | Purpose |
|---------|------|---------|
| Temporal | 7233 (gRPC), 8233 (UI) | Workflow engine |
| Gateway | 8080 | HTTP adapter for chat and approval |
| Echo worker | — | Reference app that rephrases messages |

Test it:

```bash
curl -s -X POST http://localhost:8080/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"test","text":"Hello world"}'
```

Open the Temporal UI at http://localhost:8233 to inspect workflow runs.

Stop everything:

```bash
make down
```

## HTTP API

The gateway provides a synchronous REST API. Each request blocks until
the workflow responds.

| Endpoint | Purpose |
|----------|---------|
| `POST /chat` | Start a new conversation or send a follow-up |
| `POST /approve/{workflow_id}` | Approve a pending proposal |
| `POST /reject/{workflow_id}` | Reject a pending proposal |
| `GET /health` | Health check |

### Start a conversation

```bash
curl -X POST http://localhost:8080/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"alice","text":"Hello world"}'
```

Response includes a `workflow_id`. Workers that implement the
`follow_up` signal can receive follow-up messages on the same
workflow by passing `workflow_id` in subsequent requests.

## Architecture

```
Channel (HTTP / Telegram)
    ↓
  Gateway → Temporal → App Worker
    ↑                     │
    └─── send_message ────┘
         (activity callback)
```

The gateway is stateless. Temporal owns all workflow state. Workers
register on named task queues and call gateway activities to send
responses. See [docs/architecture.md](docs/architecture.md) for details.

## Build your own worker

Use the [Echo app](examples/echo/) as a reference:

1. Create a worker with its own task queue.
2. Define workflows that accept `ChatWorkflowInput` from
   [gateway/router.py](gateway/router.py).
3. Send replies through gateway activities on the `gateway` queue.
4. Set `DEFAULT_APP` or add an `APP_ROUTES` entry to route messages
   to your worker.
5. Add your worker as a service in `docker-compose.yaml`.

## Telegram adapter

Set `CHANNEL=telegram` in `.env` and provide `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_ALLOWED_USERS`. See `.env.example` for details.

## Development

```bash
make sync       # install dependencies
make test       # run tests
make lint       # check code with ruff
make fmt        # format code with ruff
```

## License

[MIT](LICENSE)
