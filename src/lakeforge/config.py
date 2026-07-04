"""Environment-aware naming for catalogs, schemas, tables and storage paths.

All pipeline code resolves table names and paths through this module so the
same functions run against ``lakeforge_dev``, ``lakeforge_prod``, or a plain
local ``spark_catalog`` in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# OLTP tables extracted incrementally over JDBC (FR-4.2), keyed by primary key.
SQL_SOURCES: dict[str, str] = {
    "customers": "customer_id",
    "products": "product_id",
    "orders": "order_id",
    "order_lines": "order_line_id",
    "deliveries": "delivery_id",
}

# Distributor file drops in the landing volume (FR-4.1): subfolder -> format.
FILE_SOURCES: dict[str, str] = {
    "shipments": "csv",
    "returns": "json",
}


@dataclass(frozen=True)
class LakeforgeConfig:
    """Resolves fully-qualified names for one environment."""

    env: str = "dev"
    catalog: str = ""
    # Volume path with the distributor drops; empty in unit tests.
    landing_root: str = ""
    # abfss:// (or local) root for Auto Loader checkpoints and schema tracking.
    checkpoint_root: str = ""
    secret_scope: str = "kv-lakeforge"
    schemas: tuple[str, ...] = field(default=("bronze", "silver", "gold", "ops"))

    def __post_init__(self) -> None:
        if not self.catalog:
            object.__setattr__(self, "catalog", f"lakeforge_{self.env}")

    def table(self, schema: str, name: str) -> str:
        return f"{self.catalog}.{schema}.{name}"

    def landing_path(self, source: str) -> str:
        return f"{self.landing_root.rstrip('/')}/{source}"

    def checkpoint_path(self, task: str) -> str:
        return f"{self.checkpoint_root.rstrip('/')}/{self.env}/{task}"


def for_env(env: str, storage_account: str) -> LakeforgeConfig:
    """Config for a deployed environment (dev/prod) on Azure."""
    return LakeforgeConfig(
        env=env,
        landing_root=f"/Volumes/lakeforge_{env}/bronze/landing",
        checkpoint_root=f"abfss://checkpoints@{storage_account}.dfs.core.windows.net/autoloader",
    )
