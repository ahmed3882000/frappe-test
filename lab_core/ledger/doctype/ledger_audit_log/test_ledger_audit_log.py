from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from lab_core.api import get_trial_balance, post_ledger_entry
from lab_core.ledger.audit import record_ledger_audit


class TestLedgerAuditAndAPI(FrappeTestCase):
	def _make_account(self, prefix: str, account_type: str) -> str:
		code = f"{prefix}-{frappe.generate_hash(length=6).upper()}"
		doc = frappe.get_doc(
			{
				"doctype": "Ledger Account",
				"account_code": code,
				"title": f"Test {code}",
				"account_type": account_type,
			}
		).insert()
		return doc.name

	def test_doc_events_enqueue_after_commit_and_worker_is_idempotent(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")

		entry = frappe.get_doc(
			{
				"doctype": "Ledger Entry",
				"posting_date": today(),
				"reference_no": f"REF-{frappe.generate_hash(length=8)}",
				"lines": [
					{"account": cash, "direction": "Debit", "amount": 125.0},
					{"account": rev, "direction": "Credit", "amount": 125.0},
				],
			}
		).insert()

		with patch("lab_core.ledger.audit.frappe.enqueue") as mock_enqueue:
			entry.submit()

		mock_enqueue.assert_called_once()
		_, kwargs = mock_enqueue.call_args
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertTrue(kwargs["deduplicate"])
		self.assertEqual(kwargs["queue"], "short")
		self.assertEqual(kwargs["entry_name"], entry.name)
		self.assertEqual(kwargs["event_type"], "Submit")

		# Worker runs idempotently and produces an immutable audit record
		key = kwargs["idempotency_key"]
		first_audit = record_ledger_audit(entry.name, "Submit", key, triggered_by="Administrator")
		second_audit = record_ledger_audit(entry.name, "Submit", key, triggered_by="Administrator")
		self.assertIsNotNone(first_audit)
		self.assertIsNone(second_audit)

		audit_doc = frappe.get_doc("Ledger Audit Log", first_audit)
		self.assertEqual(audit_doc.total_amount, 125.0)
		audit_doc.total_amount = 999.0
		with self.assertRaises(frappe.ValidationError):
			audit_doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			audit_doc.delete(ignore_permissions=True)

	def test_whitelisted_rpc_idempotency_aggregation_and_permissions(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")
		ref = f"API-REF-{frappe.generate_hash(length=8)}"

		lines_json = frappe.as_json(
			[
				{"account": cash, "direction": "Debit", "amount": 400},
				{"account": rev, "direction": "Credit", "amount": 400},
			]
		)

		first = post_ledger_entry(posting_date=today(), reference_no=ref, lines=lines_json)
		self.assertEqual(first["status"], "posted")

		second = post_ledger_entry(posting_date=today(), reference_no=ref, lines=lines_json)
		self.assertEqual(second["status"], "already_posted")
		self.assertEqual(second["name"], first["name"])

		tb = get_trial_balance(account_type="Asset")
		matching = [row for row in tb["accounts"] if row["name"] == cash]
		self.assertEqual(len(matching), 1)
		self.assertEqual(matching[0]["balance"], 400.0)
		self.assertTrue(any(row["account_type"] == "Asset" for row in tb["summary"]))

		# Create an unprivileged user and verify @frappe.whitelist() alone does not grant access
		email = f"unpriv-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Restricted",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(email)

		with self.assertRaises(frappe.PermissionError):
			post_ledger_entry(
				posting_date=today(),
				reference_no=f"DENIED-{frappe.generate_hash(length=6)}",
				lines=lines_json,
			)
		with self.assertRaises(frappe.PermissionError):
			get_trial_balance()
