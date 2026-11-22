import frappe


def _is_privileged(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_ledger_entry_query_conditions(user: str) -> str:
	"""Filter frappe.get_list / Desk List View rows for non-privileged users."""
	if not user:
		user = frappe.session.user

	if _is_privileged(user):
		return ""

	return f"`tabLedger Entry`.owner = {frappe.db.escape(user)}"


def has_ledger_entry_permission(doc, ptype: str | None = None, user: str | None = None) -> bool | None:
	"""Enforce row-level ownership on direct get_doc / save / submit / cancel calls.

	Returning None defers to standard DocPerm role permissions; returning False denies.
	"""
	user = user or frappe.session.user
	if _is_privileged(user):
		return None

	if ptype == "create" or doc.is_new():
		return None

	return doc.owner == user
