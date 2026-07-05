"""One-time bootstrap: make sp-lakeforge-infra a Databricks workspace admin.

The Terraform pipeline (FR-6.3) plans/applies the infra/workspace stack as
sp-lakeforge-infra. Workspace objects (clusters, UC grants, secret scopes)
require the caller to be a workspace admin — and only an existing admin can
grant that, hence this human-run script rather than Terraform.

Usage (as the human workspace admin, Azure CLI logged in):
    python scripts/bootstrap_ci_workspace_admin.py
"""

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import Patch, PatchOp, PatchSchema

HOST = "https://adb-7405607941001785.5.azuredatabricks.net"
INFRA_SP_APPLICATION_ID = "a4264d6b-e789-4a9d-ae6a-7ee2377ae84b"


def main() -> None:
    w = WorkspaceClient(host=HOST, auth_type="azure-cli")
    print("authenticated as:", w.current_user.me().user_name)

    existing = list(
        w.service_principals.list(filter=f"applicationId eq '{INFRA_SP_APPLICATION_ID}'")
    )
    if existing:
        sp = existing[0]
        print("service principal already registered:", sp.id)
    else:
        sp = w.service_principals.create(
            application_id=INFRA_SP_APPLICATION_ID, display_name="sp-lakeforge-infra"
        )
        print("service principal registered:", sp.id)

    admins = next(g for g in w.groups.list(filter="displayName eq 'admins'"))
    member_ids = {m.value for m in (admins.members or [])}
    if str(sp.id) in member_ids:
        print("already a workspace admin - nothing to do")
        return

    w.groups.patch(
        admins.id,
        schemas=[PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP],
        operations=[Patch(op=PatchOp.ADD, path="members", value=[{"value": sp.id}])],
    )
    print("added to workspace admins - CI can now plan/apply the workspace stack")


if __name__ == "__main__":
    main()
