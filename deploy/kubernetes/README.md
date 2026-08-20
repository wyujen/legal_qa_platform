# Kubernetes templates

These manifests describe the runtime contract for `legal_qa_platform`; they are
not a production values bundle. They deliberately contain no namespace, Secret
object, credential value, cluster identity, or real ingress/image reference.

## Files

| File | Purpose |
|---|---|
| `configmap.yaml` | Non-sensitive internal PostgreSQL, Qdrant, and LiteLLM endpoints |
| `api-deployment.yaml` | FastAPI pods, probes, resources, hardening, and `secretKeyRef` mappings |
| `api-service.yaml` | ClusterIP service for port 8000 |
| `ui-deployment.yaml` | Streamlit REST client using the API service URL as a CLI argument |
| `ui-service.yaml` | ClusterIP service for port 8501 |
| `ingress.yaml` | Placeholder host/class/TLS routing template |
| `hpa.yaml` | Example CPU-based API scaling policy |

Kubernetes resource names use the DNS-compatible form `legal-qa-platform`;
the official project/package name remains `legal_qa_platform`.

## Operator-owned substitutions

Before applying a copy of these templates, the Human Operator supplies values
for every `<...>` placeholder through the approved deployment workflow:

- image reference/tag;
- internal service endpoints and PostgreSQL port;
- existing runtime Secret name and key mappings;
- ingress class, host, and TLS Secret reference;
- production resource, replica, and autoscaling policy after capacity testing.

Do not add a Secret manifest or real values to this directory. The application
only consumes the resulting environment variables; it does not know how the
Secret or deployment values were provisioned.

No namespace is declared. Namespace selection, image-pull credentials,
service account/RBAC, network policy, ingress policy, and TLS provisioning are
cluster decisions left to the Human Operator.

## Probe semantics

- API liveness/startup uses `/health` and only tests whether the process can
  respond.
- API readiness uses `/ready` and removes a pod from service unless the
  PostgreSQL schema/published snapshot, Qdrant service/profile collection, and
  LiteLLM gateway checks all pass.
- Streamlit uses `/_stcore/health`.
- Langfuse is fail-open and therefore is not a readiness dependency.

The API has no local persistent volume: PostgreSQL and Qdrant remain external
services. Temporary and Streamlit home paths use ephemeral `emptyDir` volumes
so containers can keep a read-only root filesystem.

## Review before production

Validate rendered manifests in the target delivery pipeline, confirm all
placeholders were replaced, and review pod resources/HPA behavior using the
documented load test. Applying manifests requires operator-controlled cluster
access; application development never requests or reads kubeconfig or Secret
values.
