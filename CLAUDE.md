# LakeForge — conventions for Claude Code

- **Language:** English only — code, docs, comments, commit messages.
- **Commits:** Conventional Commits (`feat(infra): ...`, `docs: ...`, `chore: ...`); one commit per functional requirement (FR) where practical, referencing the FR id in the body.
- **Terraform:** never run `terraform apply` or `terraform destroy` without explicit approval from the user. `fmt`, `validate`, and `plan` are always fine.
- **Secrets:** all secrets live in Azure Key Vault. Zero secrets in Git, Databricks Asset Bundle files, or pipeline variables. Subscription/tenant IDs are passed via environment variables (`ARM_SUBSCRIPTION_ID`) or `terraform.tfvars` (gitignored) — never hardcoded, this is a public repo.
- **Requirements:** the source of truth is [docs/requirements.md](docs/requirements.md). Current phase: **P1 — Foundations (E1 infra, E2 identity, E3 Unity Catalog)**.
- **Cost discipline:** target burn ≤ 300 PLN (~70 EUR)/month; destroy compute-heavy infra between sessions.
