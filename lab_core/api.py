import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.rate_limiter import rate_limit
from frappe.utils import flt

from lab_core.ledger.cache import trial_balance_cache_key
from lab_core.ledger.doctype.ledger_entry.ledger_entry import NORMAL_SIGN_BY_TYPE


@frappe.whitelist()
def post_ledger_entry(posting_date: str, reference_no: str, lines: str | list[dict]) -> dict:
	"""Create and submit a Ledger Entry idempotently by reference_no with strict permission checks."""
	frappe.has_permission("Ledger Entry", "create", throw=True)
	frappe.has_permission("Ledger Entry", "submit", throw=True)

	parsed_lines = frappe.parse_json(lines)
	if not isinstance(parsed_lines, list) or not parsed_lines:
		frappe.throw(_("`lines` must be a non-empty JSON array of line items."))

	if reference_no:
		existing = frappe.db.get_value(
			"Ledger Entry",
			{"reference_no": reference_no, "docstatus": 1},
			"name",
		)
		if existing:
			return {"name": existing, "status": "already_posted"}

	doc = frappe.get_doc(
		{
			"doctype": "Ledger Entry",
			"posting_date": posting_date,
			"reference_no": reference_no,
			"lines": [
				{
					"account": row.get("account"),
					"direction": row.get("direction"),
					"amount": flt(row.get("amount")),
				}
				for row in parsed_lines
			],
		}
	)
	doc.insert()
	doc.submit()
	return {"name": doc.name, "status": "posted"}


@frappe.whitelist()
@rate_limit(limit=60, seconds=60)
def get_trial_balance(account_type: str | None = None) -> dict:
	"""Return site-cached account balances and SQL-aggregated totals by account_type."""
	frappe.has_permission("Ledger Account", "read", throw=True)

	if account_type and account_type not in NORMAL_SIGN_BY_TYPE:
		frappe.throw(_("Invalid account_type: {0}").format(account_type))

	def _compute() -> dict:
		LedgerAccount = frappe.qb.DocType("Ledger Account")

		accounts_query = (
			frappe.qb.from_(LedgerAccount)
			.select(
				LedgerAccount.name,
				LedgerAccount.title,
				LedgerAccount.account_type,
				LedgerAccount.balance,
			)
			.orderby(LedgerAccount.name)
		)
		summary_query = (
			frappe.qb.from_(LedgerAccount)
			.select(
				LedgerAccount.account_type,
				Count(LedgerAccount.name).as_("account_count"),
				Sum(LedgerAccount.balance).as_("total_balance"),
			)
			.groupby(LedgerAccount.account_type)
			.orderby(LedgerAccount.account_type)
		)

		if account_type:
			accounts_query = accounts_query.where(LedgerAccount.account_type == account_type)
			summary_query = summary_query.where(LedgerAccount.account_type == account_type)

		return {
			"accounts": accounts_query.run(as_dict=True),
			"summary": summary_query.run(as_dict=True),
		}

	key = trial_balance_cache_key(account_type)
	result = frappe.cache.get_value(key, generator=_compute)
	if result is None:
		# Guard against same-request frappe.local.cache[key] = None poisoning from bare get_value(key) probes.
		result = _compute()
		frappe.cache.set_value(key, result)
	return result
