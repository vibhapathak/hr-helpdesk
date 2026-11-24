-- HR/IT helpdesk sample schema
CREATE TABLE employees (
    employee_id       VARCHAR(10) PRIMARY KEY CHECK (employee_id ~ '^E[0-9]{3,6}$'),
    full_name         TEXT        NOT NULL,
    department        TEXT        NOT NULL,
    job_title         TEXT        NOT NULL,
    manager_id        VARCHAR(10) REFERENCES employees(employee_id),
    location          TEXT        NOT NULL,
    employment_type   TEXT        NOT NULL CHECK (employment_type IN ('full_time', 'contract', 'intern')),
    date_of_joining   DATE        NOT NULL,
    work_email        TEXT        NOT NULL UNIQUE,
    phone             TEXT,
    -- Highly sensitive columns: the MCP server's DB role has NO grant on these.
    personal_email    TEXT,
    pan_number        CHAR(10),
    bank_account      TEXT,
    annual_salary_inr NUMERIC(12, 2)
);

CREATE TABLE leave_balances (
    employee_id      VARCHAR(10)  NOT NULL REFERENCES employees(employee_id),
    leave_year       INT          NOT NULL,
    leave_type       TEXT         NOT NULL CHECK (leave_type IN ('earned', 'sick', 'casual', 'parental')),
    entitled_days    NUMERIC(5,1) NOT NULL,
    carried_forward  NUMERIC(5,1) NOT NULL DEFAULT 0,
    used_days        NUMERIC(5,1) NOT NULL DEFAULT 0,
    pending_days     NUMERIC(5,1) NOT NULL DEFAULT 0,  -- applied for, awaiting approval
    PRIMARY KEY (employee_id, leave_year, leave_type)
);

CREATE VIEW leave_balance_summary AS
SELECT employee_id, leave_year, leave_type, entitled_days, carried_forward, used_days, pending_days,
       (entitled_days + carried_forward - used_days - pending_days) AS available_days
FROM leave_balances;

CREATE TABLE it_assets (
    asset_tag      VARCHAR(12) PRIMARY KEY,
    asset_type     TEXT        NOT NULL CHECK (asset_type IN ('laptop', 'monitor', 'phone', 'headset', 'dock', 'yubikey')),
    make_model     TEXT        NOT NULL,
    serial_number  TEXT        NOT NULL UNIQUE,
    assigned_to    VARCHAR(10) REFERENCES employees(employee_id),
    assigned_on    DATE,
    purchase_date  DATE        NOT NULL,
    warranty_end   DATE        NOT NULL,
    status         TEXT        NOT NULL CHECK (status IN ('in_use', 'in_repair', 'in_stock', 'lost', 'retired'))
);

CREATE INDEX idx_assets_assigned_to ON it_assets(assigned_to);
