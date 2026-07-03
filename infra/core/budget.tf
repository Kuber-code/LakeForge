# FR-1.10 — Budget with 50/80/100% alerts. Amount is in the subscription's
# billing currency (EUR for this subscription): 70 EUR ~ 300 PLN.
resource "azurerm_consumption_budget_resource_group" "this" {
  name              = "budget-${local.base}"
  resource_group_id = azurerm_resource_group.this.id

  amount     = var.budget_amount
  time_grain = "Monthly"

  time_period {
    # Budgets require a fixed start date (first of a month); changing it
    # forces recreation, so it is pinned, not derived from timestamp().
    start_date = "2026-07-01T00:00:00Z"
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_emails = [var.alert_email]
    }
  }
}
