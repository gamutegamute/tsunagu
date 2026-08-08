variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "create_service" {
  description = "Create the ECS Express service after the first image has been pushed."
  type        = bool
  default     = false
}

variable "application_base_url" {
  description = "ECS HTTPS URL. Leave empty for the first setup-mode deployment."
  type        = string
  default     = ""
}

variable "public_base_url" {
  description = "Optional public URL, such as a custom domain. When set, it is used for the application and Cognito callbacks."
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  type = string
}

variable "google_client_id" {
  type      = string
  sensitive = true
}

variable "google_client_secret" {
  type      = string
  sensitive = true
}

variable "hq_emails" {
  type      = list(string)
  sensitive = true
}

variable "field_emails" {
  type      = list(string)
  sensitive = true
}

variable "demo_reset_enabled" {
  description = "Enable the protected demo reset endpoint."
  type        = bool
  default     = false
}

variable "demo_admin_emails" {
  description = "HQ email addresses allowed to reset demo data."
  type        = list(string)
  default     = []
}
