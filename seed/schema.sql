-- Brewery Sales & Distribution OLTP schema (FR-1.6). Idempotent DDL.
-- All tables carry modified_at: the watermark column for incremental
-- JDBC extraction into bronze (FR-4.2).

IF OBJECT_ID('dbo.customers', 'U') IS NULL
CREATE TABLE dbo.customers (
    customer_id   INT IDENTITY(1,1) PRIMARY KEY,
    customer_name NVARCHAR(120) NOT NULL,
    city          NVARCHAR(80)  NOT NULL,
    region        NVARCHAR(40)  NOT NULL,
    segment       NVARCHAR(30)  NOT NULL,  -- HoReCa / Retail / Wholesale
    credit_limit  DECIMAL(12,2) NOT NULL DEFAULT 0,
    created_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    modified_at   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

IF OBJECT_ID('dbo.products', 'U') IS NULL
CREATE TABLE dbo.products (
    product_id  INT IDENTITY(1,1) PRIMARY KEY,
    sku         NVARCHAR(20)  NOT NULL UNIQUE,
    product_name NVARCHAR(120) NOT NULL,
    brand       NVARCHAR(60)  NOT NULL,
    category    NVARCHAR(40)  NOT NULL,   -- lager / IPA / stout / non-alcoholic ...
    unit_price  DECIMAL(9,2)  NOT NULL,
    package     NVARCHAR(30)  NOT NULL,   -- keg 30l / bottle 0.5 / can 0.5 ...
    created_at  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    modified_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

IF OBJECT_ID('dbo.orders', 'U') IS NULL
CREATE TABLE dbo.orders (
    order_id    INT IDENTITY(1,1) PRIMARY KEY,
    customer_id INT           NOT NULL REFERENCES dbo.customers(customer_id),
    order_date  DATE          NOT NULL,
    status      NVARCHAR(20)  NOT NULL,   -- placed / shipped / delivered / cancelled
    channel     NVARCHAR(20)  NOT NULL,   -- direct / distributor / online
    created_at  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    modified_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

IF OBJECT_ID('dbo.order_lines', 'U') IS NULL
CREATE TABLE dbo.order_lines (
    order_line_id INT IDENTITY(1,1) PRIMARY KEY,
    order_id      INT          NOT NULL REFERENCES dbo.orders(order_id),
    product_id    INT          NOT NULL REFERENCES dbo.products(product_id),
    quantity      INT          NOT NULL,
    unit_price    DECIMAL(9,2) NOT NULL,
    discount_pct  DECIMAL(5,2) NOT NULL DEFAULT 0,
    modified_at   DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME()
);

IF OBJECT_ID('dbo.deliveries', 'U') IS NULL
CREATE TABLE dbo.deliveries (
    delivery_id  INT IDENTITY(1,1) PRIMARY KEY,
    order_id     INT          NOT NULL REFERENCES dbo.orders(order_id),
    planned_date DATE         NOT NULL,
    actual_date  DATE         NULL,
    carrier      NVARCHAR(60) NOT NULL,
    status       NVARCHAR(20) NOT NULL,  -- scheduled / in_transit / delivered / failed
    modified_at  DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME()
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_orders_modified_at')
    CREATE INDEX ix_orders_modified_at ON dbo.orders(modified_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_order_lines_modified_at')
    CREATE INDEX ix_order_lines_modified_at ON dbo.order_lines(modified_at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_customers_modified_at')
    CREATE INDEX ix_customers_modified_at ON dbo.customers(modified_at);
