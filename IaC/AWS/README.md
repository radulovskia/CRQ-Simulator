# CRQ — DORA Cloud Exit & Portability PoC

Proof-of-concept showing that the same containerized CRQ application can run locally (Docker Compose / k3d) and on AWS EKS without AWS-specific application services.

## Architecture

```text
Docker Images (backend + frontend)
            ↓
   Kubernetes workloads
   (Namespace, Deployments, Services, Ingress)
            ↓
         EKS cluster
            ↓
   NGINX Ingress Controller
            ↓
     AWS Load Balancer
            ↓
         Internet
```

Traffic path:

```text
Internet → AWS Load Balancer → NGINX Ingress → Kubernetes Services → Frontend / Backend Pods
```

| Layer | Technology |
|-------|------------|
| Application images | `radulovskia/crq-backend:latest`, `radulovskia/crq-frontend:latest` |
| Workloads | Portable Kubernetes YAML under `AWS/kubernetes/` |
| Ingress | ingress-nginx (`ingressClassName: nginx`) |
| Cluster | Amazon EKS (managed node group) |
| Network | VPC with public/private subnets, single NAT Gateway |

Terraform provisions only the cluster and installs ingress-nginx (Helm). Application manifests stay plain YAML and are applied with `kubectl`.

## Repository layout

```text
IaC/
├── AWS/
│   ├── main.tf
│   ├── providers.tf
│   ├── versions.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars.example
│   └── kubernetes/
│       ├── namespace.yaml
│       ├── backend.yaml
│       ├── frontend.yaml
│       └── ingress.yaml
├── K3d/
│   └── crq.yaml
└── README.md
```

## Prerequisites

- Terraform >= 1.8
- AWS CLI credentials with permission to create VPC, EKS, IAM, and ELB resources
- `kubectl`
- Docker Hub images already published (`radulovskia/crq-backend:latest`, `radulovskia/crq-frontend:latest`)

## Deployment steps

### 1. Configure AWS credentials

```bash
aws configure
# or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION
```

### 2. Initialize Terraform

```bash
cd IaC/AWS
cp terraform.tfvars.example terraform.tfvars
terraform init
```

### 3. Plan

```bash
terraform plan
```

### 4. Apply infrastructure

```bash
terraform apply
```

This creates the VPC, EKS cluster, managed node group, and installs the ingress-nginx controller with a `LoadBalancer` Service (AWS creates the load balancer automatically).

### 5. Configure kubectl

```bash
aws eks update-kubeconfig --region eu-west-1 --name <cluster_name>
```

Use the `configure_kubectl` Terraform output for the exact command.

### 6. Apply Kubernetes manifests

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/backend.yaml
kubectl apply -f kubernetes/frontend.yaml
kubectl apply -f kubernetes/ingress.yaml
```

### 7. Verify

```bash
kubectl get pods -n crq
kubectl get svc -n crq
kubectl get ingress -n crq
```

Open the application using the `load_balancer_hostname` Terraform output:

```bash
terraform output load_balancer_hostname
```

Routes:

- `/` → frontend Service (port 80)
- `/mc` → backend Service (port 8000)
- `/health` → backend Service (port 8000)

## Cleanup

```bash
kubectl delete -f kubernetes/ --ignore-not-found
terraform destroy
```

Delete Kubernetes resources before destroying the cluster so the Load Balancer is cleaned up reliably.

## DORA relevance

This PoC demonstrates cloud exit and portability principles relevant to DORA (Digital Operational Resilience Act) ICT outsourcing expectations:

- **Cloud-independent containers** — the application is packaged as standard Docker images with no AWS SDK or managed-service coupling.
- **Portable Kubernetes manifests** — Namespace, Deployments, Services, and Ingress are plain YAML reusable on any conformant Kubernetes cluster (k3d, EKS, AKS, GKE).
- **Infrastructure as code** — the AWS landing zone (VPC + EKS) is recreated through Terraform and can be discarded without application rewrite.
- **Provider substitution** — migrating to another Kubernetes provider means recreating the cluster and re-applying the same manifests; the application definition does not change.
- **No proprietary application services** — no RDS, Lambda, DynamoDB, SQS, SNS, CloudFront, or other AWS-only application dependencies are used.
