# CRQ on k3d

Local Kubernetes deployment of the CRQ app using [k3d](https://k3d.io/) (k3s in Docker).

`crq.yaml` defines the same portable workloads used elsewhere in this PoC:

- Namespace `crq`
- Backend Deployment/Service (`radulovskia/crq-backend:latest`, port 8000)
- Frontend Deployment/Service (`radulovskia/crq-frontend:latest`, port 80)
- Ingress (`ingressClassName: traefik`) routing:
  - `/` → frontend
  - `/mc`, `/health` → backend

k3d ships with Traefik, so no extra ingress controller install is required.

## Prerequisites

- Docker
- [k3d](https://k3d.io/#installation)
- `kubectl`
- Images available to the cluster (`radulovskia/crq-backend:latest`, `radulovskia/crq-frontend:latest` on Docker Hub)

## Start the cluster

From this directory (`IaC/K3d`):

```bash
k3d cluster create crq -p "80:80@loadbalancer"
```

This creates a cluster named `crq` and maps host port 80 to the Traefik load balancer so Ingress HTTP works at `http://localhost`.

Confirm context:

```bash
kubectl cluster-info
kubectl get nodes
```

## Deploy the app

```bash
kubectl apply -f crq.yaml
```

Wait for pods:

```bash
kubectl get pods -n crq -w
```

## Access

Once pods are Ready:

| URL | Target |
|-----|--------|
| http://localhost/ | Frontend |
| http://localhost/mc | Backend |
| http://localhost/health | Backend health |

Useful checks:

```bash
kubectl get all,ingress -n crq
kubectl logs -n crq deploy/app
kubectl logs -n crq deploy/frontend
```

## Cleanup

```bash
kubectl delete -f crq.yaml --ignore-not-found
k3d cluster delete crq
```
