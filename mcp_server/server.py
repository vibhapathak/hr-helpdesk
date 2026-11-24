"""MCP server exposing the HR/IT Postgres database to the helpdesk agent.

Design:
* A small set of purpose-built, typed tools instead of a generic `run_sql` tool, so a
  prompt-injected LLM cannot write arbitrary SQL.
* Every query is parameterised; employee IDs are validated against a strict pattern.
* Connects as `mcp_readonly`, a Postgres role that has SELECT on non-sensitive columns
  only and a read-only default transaction (defence in depth).
"""
from __future__ import annotations

import datetime as dt
import decimal
import logging
import os
import re
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("hr-it-mcp")

DATABASE_URL = os.getenv(
    "MCP_DATABASE_URL", "postgresql://mcp_readonly:mcp_readonly_pw@localhost:5432/helpdesk"
)
EMPLOYEE_ID_RE = re.compile(r"^E\d{3,6}$")
CURRENT_LEAVE_YEAR = int(os.getenv("LEAVE_YEAR", "2026"))

mcp = FastMCP(
    "hr-it-database",
    instructions="Read-only access to employee directory, leave balances and IT assets.",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8001")),
    stateless_http=True,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value) if value % 1 else int(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{k: _jsonable(v) for k, v in row.items()} for row in rows]


def _normalise_id(employee_id: str) -> str:
    eid = (employee_id or "").strip().upper()
    if not EMPLOYEE_ID_RE.fullmatch(eid):
        raise ValueError(f"Invalid employee ID format: {employee_id!r}. Expected e.g. 'E102'.")
    return eid


@mcp.tool()
def get_employee(employee_id: str) -> dict[str, Any]:
    """Look up an employee's directory profile (name, department, title, manager,
    location, employment type, joining date, work email, phone) by employee ID like 'E102'."""
    eid = _normalise_id(employee_id)
    rows = _query(
        """SELECT e.employee_id, e.full_name, e.department, e.job_title, e.location,
                  e.employment_type, e.date_of_joining, e.work_email, e.phone,
                  e.manager_id, m.full_name AS manager_name
           FROM employees e LEFT JOIN employees m ON m.employee_id = e.manager_id
           WHERE e.employee_id = %(eid)s""",
        {"eid": eid},
    )
    if not rows:
        return {"found": False, "employee_id": eid, "message": "No employee with this ID."}
    return {"found": True, **rows[0]}


@mcp.tool()
def find_employee_by_name(name: str) -> dict[str, Any]:
    """Find employees whose name contains the given text (case-insensitive). Returns at most
    5 matches with employee ID, name, department and title. Use this to resolve a name to an ID."""
    term = (name or "").strip()
    if len(term) < 2 or len(term) > 60:
        raise ValueError("Name search term must be 2-60 characters.")
    rows = _query(
        """SELECT employee_id, full_name, department, job_title
           FROM employees WHERE full_name ILIKE %(pat)s ORDER BY full_name LIMIT 5""",
        {"pat": f"%{term}%"},
    )
    return {"matches": rows, "count": len(rows)}


@mcp.tool()
def get_leave_balance(
    employee_id: str,
    leave_type: Literal["earned", "sick", "casual", "parental", "all"] = "all",
) -> dict[str, Any]:
    """Get an employee's leave balance for the current leave year. Returns, per leave type:
    entitled_days, carried_forward, used_days, pending_days (applied but not yet approved)
    and available_days (= entitled + carried_forward - used - pending).
    Note: 'annual leave' / 'privilege leave' is stored as leave_type 'earned'."""
    eid = _normalise_id(employee_id)
    exists = _query("SELECT 1 FROM employees WHERE employee_id = %(eid)s", {"eid": eid})
    if not exists:
        return {"found": False, "employee_id": eid, "message": "No employee with this ID."}
    sql = """SELECT leave_type, entitled_days, carried_forward, used_days, pending_days, available_days
             FROM leave_balance_summary
             WHERE employee_id = %(eid)s AND leave_year = %(yr)s"""
    params: dict[str, Any] = {"eid": eid, "yr": CURRENT_LEAVE_YEAR}
    if leave_type != "all":
        sql += " AND leave_type = %(lt)s"
        params["lt"] = leave_type
    rows = _query(sql + " ORDER BY leave_type", params)
    return {"found": True, "employee_id": eid, "leave_year": CURRENT_LEAVE_YEAR, "balances": rows}


@mcp.tool()
def get_it_assets(employee_id: str) -> dict[str, Any]:
    """List IT assets currently or previously assigned to an employee: asset tag, type,
    make/model, serial number, assigned date, purchase date, warranty end, status, and the
    laptop refresh due date (purchase date + 3 years, per the IT asset policy)."""
    eid = _normalise_id(employee_id)
    exists = _query("SELECT 1 FROM employees WHERE employee_id = %(eid)s", {"eid": eid})
    if not exists:
        return {"found": False, "employee_id": eid, "message": "No employee with this ID."}
    rows = _query(
        """SELECT asset_tag, asset_type, make_model, serial_number, assigned_on, purchase_date,
                  warranty_end, status,
                  CASE WHEN asset_type = 'laptop'
                       THEN (purchase_date + INTERVAL '3 years')::date END AS refresh_due
           FROM it_assets WHERE assigned_to = %(eid)s ORDER BY asset_type, asset_tag""",
        {"eid": eid},
    )
    return {"found": True, "employee_id": eid, "assets": rows, "as_of": dt.date.today().isoformat()}


if __name__ == "__main__":
    log.info("Starting MCP server (streamable-http) on %s:%s", mcp.settings.host, mcp.settings.port)
    mcp.run(transport="streamable-http")
