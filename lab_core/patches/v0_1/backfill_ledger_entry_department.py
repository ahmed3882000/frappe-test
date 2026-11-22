import frappe


def execute() -> None:
	"""Idempotently backfill empty Ledger Entry.department values after schema sync."""
	LedgerEntry = frappe.qb.DocType("Ledger Entry")
	(
		frappe.qb.update(LedgerEntry)
		.set(LedgerEntry.department, "General")
		.where((LedgerEntry.department.isnull()) | (LedgerEntry.department == ""))
		.run()
	)
