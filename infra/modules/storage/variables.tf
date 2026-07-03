variable "base" {
  type = string
}

variable "suffix" {
  description = "Random suffix for the globally-unique storage account name."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "public_network_access_enabled" {
  description = "FR-1.8 two-step flip: true until private endpoints are validated."
  type        = bool
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
