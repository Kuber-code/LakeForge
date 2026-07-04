# Databricks notebook source
# MAGIC %md
# MAGIC # Change Data Feed demo on silver.orders (FR-4.3)
# MAGIC `silver.orders` is created with `delta.enableChangeDataFeed = true`;
# MAGIC every MERGE from bronze emits pre/post images readable below.

# COMMAND ----------

dbutils.widgets.text("env", "dev")
env = dbutils.widgets.get("env")

display(
    spark.sql(
        f"""
        SELECT _change_type, _commit_version, _commit_timestamp,
               order_id, status, modified_at
        FROM table_changes('lakeforge_{env}.silver.orders', 0)
        ORDER BY _commit_version DESC, order_id
        LIMIT 100
        """
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC Typical uses: incremental downstream consumption (gold could read only
# MAGIC changed orders instead of a full rebuild) and audit forensics
# MAGIC (who-changed-what per commit, joined to `DESCRIBE HISTORY`).
