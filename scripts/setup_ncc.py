"""FR-8 / ADR-0008 — Network Connectivity Config so the *serverless* SQL
warehouse can reach the private-endpoint storage (dashboards).

Serverless compute runs in Databricks' own network, not the customer VNet, so
the FR-1.8 storage firewall (public access disabled, default_action Deny)
blocks it. An NCC gives serverless a set of Databricks-managed private
endpoints into our storage account; once the connections are approved on the
storage side, serverless reaches the lakehouse over Azure Private Link — no
public exposure, no classic warehouse, no EDSv4 quota.

This is an **account-level** operation. The Databricks account REST API had
historically rejected this tenant's MSA identity; as of 2026-07-05 an Entra
access token for the Databricks first-party app is accepted, so this runs with
a plain ``az login`` (no account-console click-ops).

Idempotent: skips creation when an NCC of the same name already exists and
when a rule for the same (resource, group) is already present.

Usage:
    az login
    python scripts/setup_ncc.py \
        --account-id 6a072cc0-de4b-4968-839d-eb6f8945eeef \
        --workspace-id 7405607941001785 \
        --storage-resource-id /subscriptions/.../storageAccounts/stlakeforgedevsh93zt \
        --region westeurope

After the rules are created they show as PENDING connections on the storage
account — approve them (this script does it via `az` if you pass
--approve) and they converge to ESTABLISHED within a few minutes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Databricks first-party AAD application id (token audience for the account API).
DATABRICKS_APP_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
ACCOUNT_HOST = "https://accounts.azuredatabricks.net"
STORAGE_GROUPS = ("dfs", "blob")  # ADLS Gen2 sub-resources the warehouse uses


def _az_token(resource: str) -> str:
    out = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            resource,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=(sys.platform == "win32"),
    )
    return out.stdout.strip()


def _api(method: str, url: str, account_token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {account_token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url} -> HTTP {exc.code}: {exc.read().decode()}") from exc


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--account-id", required=True)
    p.add_argument("--workspace-id", required=True)
    p.add_argument("--storage-resource-id", required=True)
    p.add_argument("--region", default="westeurope")
    p.add_argument("--ncc-name", default="ncc-lakeforge-we")
    p.add_argument(
        "--approve",
        action="store_true",
        help="approve the pending private-endpoint connections via az",
    )
    args = p.parse_args()

    token = _az_token(DATABRICKS_APP_ID)
    base = f"{ACCOUNT_HOST}/api/2.0/accounts/{args.account_id}/network-connectivity-configs"

    # 1. NCC (reuse if present)
    existing = _api("GET", base, token).get("items", [])
    ncc = next((n for n in existing if n["name"] == args.ncc_name), None)
    if ncc is None:
        ncc = _api("POST", base, token, {"name": args.ncc_name, "region": args.region})
        print(f"created NCC {ncc['network_connectivity_config_id']}")
    else:
        print(f"reusing NCC {ncc['network_connectivity_config_id']}")
    ncc_id = ncc["network_connectivity_config_id"]
    rules_url = f"{base}/{ncc_id}/private-endpoint-rules"

    # 2. private-endpoint rules per sub-resource (reuse if present)
    have = _api("GET", rules_url, token).get("items", [])
    for group in STORAGE_GROUPS:
        if any(
            r.get("group_id") == group and r.get("resource_id") == args.storage_resource_id
            for r in have
        ):
            print(f"rule {group} already exists")
            continue
        r = _api(
            "POST", rules_url, token, {"resource_id": args.storage_resource_id, "group_id": group}
        )
        print(f"created rule {group}: {r['connection_state']} ({r['endpoint_name']})")

    # 3. bind NCC to the workspace
    ws_url = f"{ACCOUNT_HOST}/api/2.0/accounts/{args.account_id}/workspaces/{args.workspace_id}"
    _api("PATCH", ws_url, token, {"network_connectivity_config_id": ncc_id})
    print(f"bound workspace {args.workspace_id} -> NCC {ncc_id}")

    # 4. approve the pending connections on the storage side
    if args.approve:
        pending = json.loads(
            subprocess.run(
                [
                    "az",
                    "network",
                    "private-endpoint-connection",
                    "list",
                    "--id",
                    args.storage_resource_id,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
                shell=(sys.platform == "win32"),
            ).stdout
        )
        for pc in pending:
            if pc["properties"]["privateLinkServiceConnectionState"]["status"] == "Pending":
                subprocess.run(
                    [
                        "az",
                        "network",
                        "private-endpoint-connection",
                        "approve",
                        "--id",
                        pc["id"],
                        "--description",
                        "NCC serverless (LakeForge)",
                        "-o",
                        "none",
                    ],
                    check=True,
                    shell=(sys.platform == "win32"),
                )
                print(f"approved {pc['name']}")

    # 5. report convergence
    for _ in range(16):
        states = {
            r["group_id"]: r["connection_state"]
            for r in _api("GET", rules_url, token).get("items", [])
        }
        print("states:", states)
        if states and all(s == "ESTABLISHED" for s in states.values()):
            print("NCC ready — serverless can now reach private storage")
            return
        time.sleep(30)
    print("rules not all ESTABLISHED yet; approve pending connections and re-check")


if __name__ == "__main__":
    main()
