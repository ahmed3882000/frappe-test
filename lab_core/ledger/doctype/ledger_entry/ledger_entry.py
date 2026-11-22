import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Debit-normal accounts increase on Debit (+1 for Debit - Credit);
# credit-normal accounts increase on Credit (-1 for Debit - Credit).
NORMAL_SIGN_BY_TYPE = {
	"Asset": 1,
	"Expense": 1,
	"Liability": -1,
	"Revenue": -1,
}


class LedgerEntry(Document):
	"""Submittable double-entry journal posting that atomically updates account balances."""

	def validate(self) -> None:
		if len(self.lines) < 2:
			frappe.throw(_("Ledger Entry requires at least 2 lines."))

		precision = self.precision("amount", "lines") or 2
		total_debit = 0.0
		total_credit = 0.0

		for line in self.lines:
			amount = flt(line.amount, precision)
			if amount <= 0:
				frappe.throw(_("Row #{0}: Amount must be greater than zero.").format(line.idx))

			if line.direction == "Debit":
				total_debit = flt(total_debit + amount, precision)
			elif line.direction == "Credit":
				total_credit = flt(total_credit + amount, precision)
			else:
				frappe.throw(_("Row #{0}: Direction must be Debit or Credit.").format(line.idx))

		if flt(total_debit, precision) != flt(total_credit, precision):
			frappe.throw(
				_("Ledger Entry is unbalanced: total Debit ({0}) != total Credit ({1}).").format(
					total_debit, total_credit
				)
			)

	def on_submit(self) -> None:
		self._apply_balance_updates(sign=1)

	def on_cancel(self) -> None:
		self._apply_balance_updates(sign=-1)

	def _apply_balance_updates(self, sign: int) -> None:
		"""Apply or reverse net debit-credit deltas per account under deterministic row locks."""
		precision = self.precision("amount", "lines") or 2
		net_debit_minus_credit: dict[str, float] = {}

		for line in self.lines:
			amount = flt(line.amount, precision)
			signed_amount = amount if line.direction == "Debit" else -amount
			net_debit_minus_credit[line.account] = flt(
				net_debit_minus_credit.get(line.account, 0.0) + signed_amount, precision
			)

		account_names = sorted(net_debit_minus_credit)
		if not account_names:
			return

		LedgerAccount = frappe.qb.DocType("Ledger Account")
		# Canonical ORDER BY + FOR UPDATE prevents lost updates and AB-BA deadlocks.
		locked_accounts = (
			frappe.qb.from_(LedgerAccount)
			.select(LedgerAccount.name, LedgerAccount.account_type)
			.where(LedgerAccount.name.isin(account_names))
			.orderby(LedgerAccount.name)
			.for_update()
			.run(as_dict=True)
		)

		account_types = {row.name: row.account_type for row in locked_accounts}
		for account_name in account_names:
			account_type = account_types.get(account_name)
			if account_type not in NORMAL_SIGN_BY_TYPE:
				frappe.throw(_("Unknown account type for Ledger Account {0}.").format(account_name))

			delta = flt(
				net_debit_minus_credit[account_name] * NORMAL_SIGN_BY_TYPE[account_type] * sign,
				precision,
			)
			if not delta:
				continue

			(
				frappe.qb.update(LedgerAccount)
				.set(LedgerAccount.balance, LedgerAccount.balance + delta)
				.where(LedgerAccount.name == account_name)
				.run()
			)
			frappe.clear_document_cache("Ledger Account", account_name)
