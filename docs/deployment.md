# Kubernetes deployment

This repository supplies two independent Kustomize packages:

- `deploy/gateway`: the platform Gateway.
- `examples/echo/deploy`: an optional reference worker.

Temporal, model serving, cluster configuration, and Argo CD Applications belong
to the infrastructure repository. Neither package creates a Namespace, Secret,
Service, ingress, or database. The Gateway package has no dependency on Echo.

## Configure the deployment

Point an Argo CD Application at this repository and the required package path.
Set its destination namespace and enable `CreateNamespace=true`. Use Kustomize
patches in the infrastructure repository to set each ConfigMap and a pod-template
`agent-platform/config-hash` annotation. Compute the annotation as SHA-256 of
canonical JSON configuration (sorted keys, compact separators). This triggers a
rollout when configuration changes.

Gateway settings:

| Setting | Purpose |
|---|---|
| `TEMPORAL_ADDRESS` | Reachable Temporal frontend host and port. |
| `TEMPORAL_NAMESPACE` | Existing Temporal namespace. |
| `GATEWAY_TASK_QUEUE` | Queue for messaging activities; normally `gateway`. |
| `DEFAULT_APP` | Required default JSON workflow route. |
| `APP_ROUTES` | JSON object mapping text prefixes to workflow routes. |
| `TELEGRAM_ALLOWED_USERS` | Nonempty JSON array of authorized numeric user IDs. |

The Gateway reads `TELEGRAM_BOT_TOKEN` from the Kubernetes Secret
`agent-gateway-credentials`, key `TELEGRAM_BOT_TOKEN`. Provision that Secret
outside Git. The base allowlist is empty, so the Gateway refuses to start until
you supply at least one positive Telegram user ID. This requirement also applies
to local development.

Echo uses `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TASK_QUEUE=echo`,
`LLM_BASE_URL`, and `LLM_MODEL`. It needs no Telegram credentials. Its example
workflow currently requires queues named `echo` and `gateway`. Its model call
uses API key `not-needed` and the `chat_template_kwargs.enable_thinking=false`
option. Use a compatible endpoint.

For private images, provision a registry pull Secret in the destination
namespace and add its name through a pod `imagePullSecrets` patch. Argo CD's Git
credentials are separate from the kubelet's registry credentials.

## Build and release

Python dependencies are pinned in `uv.lock`. `requirements.lock` is its hashed
runtime export, used by both Docker targets. Update both files together:

```bash
uv lock
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
```

The Python base image is pinned by digest. Review changes to that digest like a
dependency upgrade. The build context permits only runtime sources and locked
dependencies; local settings and credentials are excluded.

```bash
docker build --platform linux/amd64 --target gateway -t agent-platform:test .
docker build --platform linux/amd64 --target echo -t agent-platform-echo:test .
```

The `Platform images` workflow tests pull requests without publishing. On main,
it publishes verified images tagged `sha-<full Git commit>` to GHCR. Builds always run before publication. A separate main-branch job publishes the
tested image artifact; PR jobs have no package write permission. Existing release
tags are retained on rerun; an unexpected registry error stops publication.
The workflow summary records each digest. Images carry their source revision
and repository as OCI labels. Publication does not deploy a release.

In the infrastructure repository, pin the Application's `source.targetRevision`
to the release's full Git commit and `source.kustomize.images` to the matching
image digest. Keep the source image name unchanged on the left of the override:

```yaml
kustomize:
  images:
    - ghcr.io/pycaster/agent-platform=ghcr.io/pycaster/agent-platform@sha256:<published-digest>
```

Replace the example digest before committing. Publish images first, then update
both release pins in the infrastructure repository. Do not deploy moving tags
or branches. Argo CD reconciles that infrastructure change.

## Cutover and operation

Stop any local Gateway using the same bot before deploying it to Kubernetes.
Stop local Echo workers while checking that work runs in the cluster. The
Gateway has one replica and uses `Recreate` to avoid two pollers during upgrades.
Do not scale it above one or run another instance with the same bot token.

SIGINT and SIGTERM use normal worker cleanup. Temporal activity shutdown has a
40-second grace period inside Kubernetes' 60-second termination allowance.
Containers run as a non-root user with a read-only root filesystem and a small
writable `/tmp`. They do not receive Kubernetes API credentials.

Pod readiness alone does not prove Temporal or Telegram connectivity. Check
Temporal task queue pollers, workflow history, and Gateway logs. No HTTP health
endpoint is provided. Do not expose a Service just to make an unrelated TCP
probe pass. Telegram polling currently drops queued updates on startup, so
cutover and restart can lose messages received during downtime. Retries can
also repeat external effects; this release does not promise exactly-once delivery.

After bot Secret rotation, perform a controlled Gateway Deployment restart.
Do not print bot tokens or raw HTTP request logs that can contain them.

## Validate and roll back

Render both packages and run the tests before release:

```bash
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q
kubectl kustomize deploy/gateway
kubectl kustomize examples/echo/deploy
```

CI also checks Kubernetes schemas and tests imports and file contents in the
final non-root images. Deployment validation must check the final configuration,
image digests, Temporal pollers, chat output, all three proposal results, and
recovery of a waiting workflow after replacing its worker.

Use clearly labeled test messages only in the operator's private test chat.
A direct Temporal signal checks workflow behavior, not a Telegram button tap.
Mocked inbound Updates check handler logic, not live Telegram delivery. Record
these limits with the deployment results.

To roll back, restore the previous manifest commit, image digest, and required
configuration in the infrastructure repository. Let Argo CD reconcile. Keep
previous images available. For a failed first deployment, remove only the new
workloads through GitOps and restore any local processes stopped for cutover.
Do not delete shared namespaces, Secrets, or Temporal data.

## Replace the example app

Deploy your app worker separately, then update Gateway routing in your
infrastructure repository. Verify the route and let open Echo workflows finish
before removing the Echo Application. Keep historical images for rollback.
The Gateway package does not require Echo, and the reference example can remain
in this repository for other users.

## Explicit workflow routing

A route can select both a task queue and workflow type:

```json
{"reports":{"task_queue":"reports","workflow_type":"ReportSummaryWorkflow"}}
```

Set this JSON as `APP_ROUTES`. `DEFAULT_APP` requires one route object encoded as JSON. A structured route requires nonempty
`task_queue` and `workflow_type` fields. Optional `proposal_workflow_type`
enables `/propose` for that route; omitting it or setting it to null disables
proposals and returns an explanation without starting a workflow.

Queue strings are rejected at startup. Workflow names are never inferred from
a queue name. Prefix matching is case-insensitive; the first matching
entry wins, and unmatched messages use `DEFAULT_APP`. Original text is passed
unchanged. This changes workflow dispatch only, not the chat input or reply
activity contract.

Register a new workflow type on the app worker before switching its route.
Upgrade the Gateway image and both routing settings together. Older images
accept only strings; this version requires route objects. Drain existing app
executions before removing their workflow registrations. Historical workflow
types are not renamed.

For the bundled Echo example, configure the default explicitly:

```text
DEFAULT_APP={"task_queue":"echo","workflow_type":"ChatWorkflow","proposal_workflow_type":"ProposalWorkflow"}
```

These are Echo's registered names, not reserved platform names. Other apps can
register any workflow type that accepts the Gateway chat input contract.
