terraform {
  required_version = ">= 1.8.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.46"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}

variable "state_bucket_name" {
  type = string
}

variable "github_repository" {
  description = "GitHub repository in owner/name format."
  type        = string
  default     = "NxTEND-THE-HACK/2026-Team-11"
}

variable "github_oidc_subject" {
  description = "Exact GitHub OIDC subject. Leave empty to use the production environment subject derived from github_repository."
  type        = string
  default     = ""
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN. Leave empty to create one."
  type        = string
  default     = ""
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = var.state_bucket_name
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_oidc_provider_arn == "" ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_provider_arn = var.github_oidc_provider_arn != "" ? var.github_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
  github_oidc_subject      = var.github_oidc_subject != "" ? var.github_oidc_subject : "repo:${var.github_repository}:environment:production"
}

resource "aws_iam_role" "github_deploy" {
  name = "tsunagu-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = local.github_oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.github_oidc_subject
        }
      }
    }]
  })
}

# デプロイ専用Roleには、TSUNAGUの構築に必要な権限だけを付与する。
# 信頼ポリシーは対象リポジトリのproduction Environmentだけに限定する。
resource "aws_iam_role_policy" "github_deploy" {
  name = "tsunagu-production-deploy"
  role = aws_iam_role.github_deploy.id

  # GitHub Actionsには、TSUNAGUの構築に必要なサービスだけを許可する。
  # IAMユーザー、Organizations、請求情報などのアカウント管理権限は与えない。
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetBucketVersioning",
          "s3:GetEncryptionConfiguration",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*",
        ]
      },
      {
        Sid    = "ReadNetworkConfiguration"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcAttribute",
          "ec2:DescribeVpcs",
        ]
        Resource = "*"
      },
      {
        Sid    = "ManageSecurityGroups"
        Effect = "Allow"
        Action = [
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:CreateSecurityGroup",
          "ec2:CreateTags",
          "ec2:DeleteSecurityGroup",
          "ec2:DeleteTags",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
        ]
        Resource = "*"
      },
      {
        Sid    = "ManageTSUNAGUContainerResources"
        Effect = "Allow"
        Action = [
          "ecr:*",
          "ecs:*",
          "application-autoscaling:*",
          "elasticloadbalancing:*",
        ]
        Resource = "*"
      },
      {
        Sid      = "GetECRAuthorizationToken"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "ManageTSUNAGUDatabase"
        Effect = "Allow"
        Action = [
          "rds:AddTagsToResource",
          "rds:CreateDBInstance",
          "rds:CreateDBSubnetGroup",
          "rds:DeleteDBInstance",
          "rds:DeleteDBSubnetGroup",
          "rds:DescribeDBInstances",
          "rds:DescribeDBSubnetGroups",
          "rds:DescribeOrderableDBInstanceOptions",
          "rds:ListTagsForResource",
          "rds:ModifyDBInstance",
          "rds:ModifyDBSubnetGroup",
          "rds:RemoveTagsFromResource",
        ]
        Resource = "*"
      },
      {
        Sid      = "ManageTSUNAGUAuthentication"
        Effect   = "Allow"
        Action   = "cognito-idp:*"
        Resource = "*"
      },
      {
        Sid      = "DescribeSSMParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        Sid    = "ManageTSUNAGUParameters"
        Effect = "Allow"
        Action = [
          "ssm:AddTagsToResource",
          "ssm:DeleteParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:ListTagsForResource",
          "ssm:PutParameter",
          "ssm:RemoveTagsFromResource",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/tsunagu/*"
      },
      {
        Sid    = "ManageTSUNAGULogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:ListTagsForResource",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
        ]
        Resource = "*"
      },
      {
        Sid    = "ManageTSUNAGURoles"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListRolePolicies",
          "iam:PassRole",
          "iam:PutRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:UpdateAssumeRolePolicy",
        ]
        Resource = "arn:aws:iam::*:role/tsunagu-*"
      },
    ]
  })
}

output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.id
}

output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
