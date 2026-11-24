#!/bin/bash
# Least-privilege role for the MCP server: SELECT only, and only on non-sensitive columns.
# Even if the agent were tricked into requesting PAN / salary / bank data, Postgres itself refuses.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE ROLE mcp_readonly LOGIN PASSWORD '${MCP_DB_PASSWORD:-mcp_readonly_pw}';
  GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO mcp_readonly;
  GRANT USAGE ON SCHEMA public TO mcp_readonly;
  GRANT SELECT (employee_id, full_name, department, job_title, manager_id, location,
                employment_type, date_of_joining, work_email, phone)
        ON employees TO mcp_readonly;
  GRANT SELECT ON leave_balances, leave_balance_summary, it_assets TO mcp_readonly;
  ALTER ROLE mcp_readonly SET default_transaction_read_only = on;
  ALTER ROLE mcp_readonly SET statement_timeout = '5s';
SQL
