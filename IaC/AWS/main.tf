data "aws_availability_zones" "available" {
  state = "available"

  # Exclude Local Zones / Wavelength — only standard regional AZs.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 2
}

locals {
  cluster_name = "${var.cluster_name_prefix}-${random_id.suffix.hex}"
  azs          = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${local.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = 1
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"             = 1
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  # Skip KMS key creation for a simpler, faster apply (secrets use AWS-managed encryption).
  create_kms_key            = false
  cluster_encryption_config = {}

  # Allow the identity running Terraform to manage the cluster after creation.
  # Note: this only covers the Terraform principal (e.g. IAM user/role), NOT
  # the account root used in the AWS console — add an explicit access entry below.
  enable_cluster_creator_admin_permissions = true

  # Console "root" / account principal: an access entry without a policy
  # association still shows as no Kubernetes access in the EKS console.
  access_entries = {
    root = {
      principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      type          = "STANDARD"

      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  eks_managed_node_groups = {
    default = {
      instance_types = var.node_instance_types
      min_size       = 1
      max_size       = 2
      desired_size   = var.node_desired_size
      subnet_ids     = module.vpc.private_subnets

      # Smaller root volume speeds instance launch slightly for a lab cluster.
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size = 20
            volume_type = "gp3"
            encrypted   = true
          }
        }
      }
    }
  }
}

resource "helm_release" "ingress_nginx" {
  name             = "ingress-nginx"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  namespace        = "ingress-nginx"
  create_namespace = true
  version          = "4.11.3"

  # Allow time for nodes + AWS NLB to become ready.
  timeout = 600
  wait    = true

  set {
    name  = "controller.service.type"
    value = "LoadBalancer"
  }

  # NLB provisions faster and more reliably than Classic ELB on modern EKS.
  set {
    name  = "controller.service.annotations.service\\.beta\\.kubernetes\\.io/aws-load-balancer-type"
    value = "nlb"
  }

  depends_on = [module.eks]
}

data "kubernetes_service_v1" "ingress_nginx" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }

  depends_on = [helm_release.ingress_nginx]
}
