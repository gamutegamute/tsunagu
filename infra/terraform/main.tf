data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_ecr_repository" "app" {
  name                 = "tsunagu"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the latest 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "random_password" "database" {
  length  = 32
  special = false
}

resource "random_password" "session" {
  length  = 64
  special = false
}

resource "random_password" "gateway" {
  length  = 48
  special = false
}

resource "aws_security_group" "app" {
  name        = "tsunagu-app"
  description = "ECS Express tasks"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name        = "tsunagu-database"
  description = "PostgreSQL from TSUNAGU tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "tsunagu"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "main" {
  identifier                 = "tsunagu"
  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = "db.t4g.micro"
  allocated_storage          = 20
  max_allocated_storage      = 50
  storage_encrypted          = true
  db_name                    = "tsunagu"
  username                   = "tsunagu"
  password                   = random_password.database.result
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.database.id]
  publicly_accessible        = false
  backup_retention_period    = 7
  deletion_protection        = false
  skip_final_snapshot        = true
  auto_minor_version_upgrade = true
  apply_immediately          = true
}

locals {
  database_url = "postgresql://tsunagu:${random_password.database.result}@${aws_db_instance.main.address}:5432/tsunagu"
  callback_urls = concat(
    ["http://localhost:8000/api/auth/callback"],
    var.application_base_url == "" ? [] : ["${trimsuffix(var.application_base_url, "/")}/api/auth/callback"]
  )
  logout_urls = concat(
    ["http://localhost:8000/login"],
    var.application_base_url == "" ? [] : ["${trimsuffix(var.application_base_url, "/")}/login"]
  )
}

resource "aws_ssm_parameter" "database_url" {
  name  = "/tsunagu/production/database-url"
  type  = "SecureString"
  value = local.database_url
}

resource "aws_ssm_parameter" "session_secret" {
  name  = "/tsunagu/production/session-secret"
  type  = "SecureString"
  value = random_password.session.result
}

resource "aws_ssm_parameter" "gateway_key" {
  name  = "/tsunagu/production/gateway-api-key"
  type  = "SecureString"
  value = random_password.gateway.result
}

resource "aws_cognito_user_pool" "main" {
  name = "tsunagu"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email    = "email"
    name     = "name"
    username = "sub"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "tsunagu-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = [aws_cognito_identity_provider.google.provider_name]
  callback_urls                        = local.callback_urls
  logout_urls                          = local.logout_urls
  prevent_user_existence_errors        = "ENABLED"
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/tsunagu"
  retention_in_days = 7
}

resource "aws_iam_role" "execution" {
  name = "tsunagu-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:GetParameters"]
      Resource = [
        aws_ssm_parameter.database_url.arn,
        aws_ssm_parameter.session_secret.arn,
        aws_ssm_parameter.gateway_key.arn,
      ]
    }]
  })
}

resource "aws_iam_role" "infrastructure" {
  name = "tsunagu-ecs-express-infrastructure"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "infrastructure" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_ecs_express_gateway_service" "app" {
  count                   = var.create_service ? 1 : 0
  service_name            = "tsunagu"
  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn
  health_check_path       = "/health"
  cpu                     = "256"
  memory                  = "512"

  primary_container {
    image          = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    container_port = 8000

    aws_logs_configuration {
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "app"
    }

    environment {
      name  = "APP_ENV"
      value = "production"
    }
    environment {
      name  = "AUTH_MODE"
      value = var.application_base_url == "" ? "setup" : "cognito"
    }
    environment {
      name  = "PUBLIC_BASE_URL"
      value = var.application_base_url
    }
    environment {
      name  = "SESSION_HOURS"
      value = "24"
    }
    environment {
      name  = "DEMO_SEED"
      value = "false"
    }
    environment {
      name  = "COGNITO_DOMAIN"
      value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    }
    environment {
      name  = "COGNITO_CLIENT_ID"
      value = aws_cognito_user_pool_client.web.id
    }
    environment {
      name  = "COGNITO_ISSUER"
      value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
    }
    environment {
      name  = "AUTH_HQ_EMAILS"
      value = join(",", [for email in var.hq_emails : lower(email)])
    }
    environment {
      name  = "AUTH_FIELD_EMAILS"
      value = join(",", [for email in var.field_emails : lower(email)])
    }

    secret {
      name       = "DATABASE_URL"
      value_from = aws_ssm_parameter.database_url.arn
    }
    secret {
      name       = "SESSION_SECRET"
      value_from = aws_ssm_parameter.session_secret.arn
    }
    secret {
      name       = "GATEWAY_API_KEY"
      value_from = aws_ssm_parameter.gateway_key.arn
    }
  }

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.app.id]
  }

  scaling_target {
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 60
    min_task_count            = 1
    max_task_count            = 2
  }

  depends_on = [
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy_attachment.infrastructure,
  ]
}
