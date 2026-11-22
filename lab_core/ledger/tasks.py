import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def verify_ledger_integrity() -> list[str]:
	"""Daily reconciliation job: detect any submitted Ledger Entry with Debit != Credit."""
	LedgerEntry = frappe.qb.DocType("Ledger Entry")
	LedgerLine = frappe.qb.DocType("Ledger Entry Line")

	net_expr = Case().when(LedgerLine.direction == "Debit", LedgerLine.amount).else_(-LedgerLine.amount)

	rows = (
		frappe.qb.from_(LedgerEntry)
		.inner_join(LedgerLine)
		.on(LedgerLine.parent == LedgerEntry.name)
		.select(
			LedgerEntry.name,
			Sum(net_expr).as_("net_diff"),
		)
		.where(LedgerEntry.docstatus == 1)
		.groupby(LedgerEntry.name)
		.run(as_dict=True)
	)

	mismatched = [row.name for row in rows if flt(row.net_diff, 2) != 0.0]
	if mismatched:
		frappe.log_error(
			title="Ledger Integrity Mismatch",
			message=f"Unbalanced submitted Ledger Entries detected: {', '.join(mismatched)}",
		)
	return mismatched
