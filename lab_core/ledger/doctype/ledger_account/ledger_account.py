import frappe
from frappe import _
from frappe.model.document import Document


class LedgerAccount(Document):
	"""Chart-of-accounts record whose balance is mutated only by submitted Ledger Entries."""

	def before_insert(self) -> None:
		# Prevent callers from seeding an arbitrary initial balance outside ledger postings.
		self.balance = 0.0

	def validate(self) -> None:
		if self.account_code:
			self.account_code = self.account_code.strip().upper()

		if not self.is_new() and self.has_value_changed("balance"):
			frappe.throw(_("Account balance cannot be edited directly; post a Ledger Entry instead."))
