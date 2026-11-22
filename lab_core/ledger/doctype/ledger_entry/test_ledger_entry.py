import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestLedgerEntry(FrappeTestCase):
	def _make_account(self, prefix: str, account_type: str) -> str:
		code = f"{prefix}-{frappe.generate_hash(length=6).upper()}"
		doc = frappe.get_doc(
			{
				"doctype": "Ledger Account",
				"account_code": code,
				"title": f"Test {code}",
				"account_type": account_type,
				"balance": 999,  # before_insert must force initial balance to 0
			}
		).insert()
		return doc.name

	def _make_entry(self, lines: list[dict], reference_no: str | None = None):
		return frappe.get_doc(
			{
				"doctype": "Ledger Entry",
				"posting_date": today(),
				"reference_no": reference_no or f"REF-{frappe.generate_hash(length=8)}",
				"lines": lines,
			}
		)

	def test_initial_balance_forced_zero_and_direct_edit_blocked(self):
		cash = self._make_account("CASH", "Asset")
		acc = frappe.get_doc("Ledger Account", cash)
		self.assertEqual(acc.balance, 0.0)

		acc.balance = 500.0
		with self.assertRaises(frappe.ValidationError):
			acc.save()

	def test_unbalanced_and_non_positive_entries_rejected(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")

		unbalanced = self._make_entry(
			[
				{"account": cash, "direction": "Debit", "amount": 100},
				{"account": rev, "direction": "Credit", "amount": 90},
			]
		)
		with self.assertRaises(frappe.ValidationError):
			unbalanced.insert()

		non_positive = self._make_entry(
			[
				{"account": cash, "direction": "Debit", "amount": 0},
				{"account": rev, "direction": "Credit", "amount": 0},
			]
		)
		with self.assertRaises(frappe.ValidationError):
			non_positive.insert()

	def test_submit_and_cancel_update_balances_and_lock_document(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")

		entry = self._make_entry(
			[
				{"account": cash, "direction": "Debit", "amount": 250.50},
				{"account": rev, "direction": "Credit", "amount": 250.50},
			]
		).insert()
		entry.submit()

		self.assertEqual(frappe.db.get_value("Ledger Account", cash, "balance"), 250.50)
		self.assertEqual(frappe.db.get_value("Ledger Account", rev, "balance"), 250.50)

		# Submitted docs cannot be mutated via save() or deleted
		entry.reference_no = "TAMPERED"
		with self.assertRaises(frappe.UpdateAfterSubmitError):
			entry.save()
		with self.assertRaises(frappe.ValidationError):
			entry.delete()

		entry.reload()
		entry.cancel()

		self.assertEqual(frappe.db.get_value("Ledger Account", cash, "balance"), 0.0)
		self.assertEqual(frappe.db.get_value("Ledger Account", rev, "balance"), 0.0)
