variable "aws_region" {
  type        = string
  description = "AWS region for the EKS cluster."
  default     = "eu-west-1"
}

variable "cluster_name_prefix" {
  type        = string
  description = "Prefix used to generate the EKS cluster name."
  default     = "crq"
}

variable "cluster_version" {
  type        = string
  description = "Kubernetes version for the EKS cluster. Must be at least 1.36 (EKS-supported)."
  default     = "1.36"

  validation {
    condition = (
      tonumber(split(".", var.cluster_version)[0]) > 1 ||
      (
        tonumber(split(".", var.cluster_version)[0]) == 1 &&
        tonumber(split(".", var.cluster_version)[1]) >= 36
      )
    )
    error_message = "cluster_version must be at least 1.36."
  }
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
  default     = "10.0.0.0/16"
}

variable "node_instance_types" {
  type        = list(string)
  description = "EC2 instance types for the managed node group."
  # t3.small is Free Tier–eligible on this account. t3.medium is rejected by EC2
  # ("not eligible for Free Tier"), which leaves the node group stuck in CREATING.
  default = ["t3.small"]
}

variable "node_desired_size" {
  type        = number
  description = "Desired number of worker nodes."
  default     = 1
}
