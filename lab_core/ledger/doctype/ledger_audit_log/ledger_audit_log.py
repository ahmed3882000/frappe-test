import frappe
from frappe import _
from frappe.model.document import Document


class LedgerAuditLog(Document):
	"""Append-only audit log written asynchronously by ledger doc_events workers."""

	def before_save(self) -> None:
		if not self.is_new():
			frappe.throw(_("Ledger Audit Log records are immutable."))

	def on_trash(self) -> None:
		if not frappe.flags.allow_audit_cleanup:
			frappe.throw(_("Ledger Audit Log records cannot be deleted."))
