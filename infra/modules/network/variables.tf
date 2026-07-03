variable "base" {
  description = "Naming base, e.g. lakeforge-dev."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "address_space" {
  type = string
}

variable "subnet_cidrs" {
  type = object({
    dbx_host      = string
    dbx_container = string
    privatelink   = string
  })
}

variable "tags" {
  type    = map(string)
  default = {}
}
