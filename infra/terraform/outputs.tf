output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "application_url" {
  value = var.create_service ? aws_ecs_express_gateway_service.app[0].ingress_paths[0].endpoint : null
}

output "cognito_google_callback_url" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/idpresponse"
}

output "gateway_api_key_parameter" {
  value = aws_ssm_parameter.gateway_key.name
}
