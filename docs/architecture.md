# Architecture

This repository provides a Telegram Gateway and an Echo reference app. Temporal
is an external service. App workers can live in separate repositories and do
not need to import the Gateway's Python package.

## Request and reply flow

1. The Gateway polls Telegram and checks the sender against its nonempty allowlist.
2. It selects the first matching text prefix from `APP_ROUTES`, ignoring case.
   Unmatched messages use `DEFAULT_APP`.
3. The selected route supplies a task queue and workflow type. The Gateway asks
   Temporal to start a new execution with the original message and sender fields.
4. An app worker polling that queue runs its workflow and activities.
5. The app schedules a messaging activity on the Gateway's activity queue.
6. The Gateway executes that activity and sends the Telegram reply.

Temporal owns the queues and workflow histories. Workers poll named queues;
there is no separate queue creation step. A workflow type is the name registered
by a worker. A workflow ID identifies an execution; apps do not share an execution
merely because they register the same type name.

## Route configuration

`DEFAULT_APP` is a required JSON object. `APP_ROUTES` is a JSON map of text
prefixes to objects with these fields:

| Field | Meaning |
|---|---|
| `task_queue` | Queue polled by the app worker. |
| `workflow_type` | Registered workflow type for chat requests. |
| `proposal_workflow_type` | Optional registered type for `/propose` requests. |

Queue-only strings are rejected. Workflow names are app choices, not platform
constants. See [configuration examples](deployment.md#explicit-workflow-routing).
The adapter handles `/start` and `/propose`; arbitrary slash commands are not
registered. Text prefixes such as `reports` work without changing the adapter.

## App contracts

A chat or proposal workflow receives a JSON-compatible object:

```json
{"chat_id": 42, "user_id": 42, "username": null, "text": "reports summary"}
```

Field definitions live in [gateway/router.py](../gateway/router.py). Apps register
their own workflow types, accept this input, and put external operations in
activities. The Gateway does not run model inference or own app credentials.

Messaging activity inputs are defined in
[gateway/activities.py](../gateway/activities.py):

- `send_message`: chat ID, text, and optional parse mode.
- `send_approval_request`: chat ID, workflow ID, proposal details, and button labels.
- `send_alert`: chat ID, text, and optional parse mode.

The Gateway activity queue defaults to `gateway`. Apps must use the same queue
and Temporal namespace as the Gateway. The bundled Echo example uses fixed
`echo` and `gateway` queues. The `sdk` currently contains process shutdown helpers,
not an app registry, installer, or policy engine.

## Approval flow

`/propose` selects a route using the text after the command. If that route has no
proposal workflow type, the Gateway replies that proposals are unsupported and
does not start a workflow.

An app proposal workflow can send approval buttons through the Gateway. Button
callbacks contain the workflow ID and decision. The Gateway checks the sender's
allowlist membership and decision code, then sends an `approval` signal containing
`decision`, `user_id`, and `timestamp`. The app owns timeout handling, any further
authorization, and the operation performed after approval. Echo waits five minutes
and sends a confirmation; it does not change an external system.

## Runtime boundaries

Run one Gateway per bot token. Apps run separately and need not use a model.
Task queues route work; they are not authorization boundaries. Infrastructure
must protect Temporal access, workflow history, and each app's credentials.

Telegram polling drops queued updates at startup. Activity retries can repeat
external effects. The implementation does not promise exactly-once delivery.
See [deployment](deployment.md) for graceful shutdown, container restrictions,
release pins, and operational checks.
