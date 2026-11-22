import frappe
from frappe.permissions import add_permission, update_permission_property
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from lab_core.api import get_trial_balance
from lab_core.ledger.cache import invalidate_trial_balance_cache, trial_balance_cache_key
from lab_core.ledger.tasks import verify_ledger_integrity
from lab_core.patches.v0_1.backfill_ledger_entry_department import execute as run_department_patch


class TestSecurityCacheAndTasks(FrappeTestCase):
	def _make_account(self, prefix: str, account_type: str) -> str:
		code = f"{prefix}-{frappe.generate_hash(length=6).upper()}"
		return (
			frappe.get_doc(
				{
					"doctype": "Ledger Account",
					"account_code": code,
					"title": f"Test {code}",
					"account_type": account_type,
				}
			)
			.insert()
			.name
		)

	def _make_entry(self, cash: str, rev: str, amount: float = 100.0):
		return frappe.get_doc(
			{
				"doctype": "Ledger Entry",
				"posting_date": today(),
				"reference_no": f"SEC-{frappe.generate_hash(length=8)}",
				"lines": [
					{"account": cash, "direction": "Debit", "amount": amount},
					{"account": rev, "direction": "Credit", "amount": amount},
				],
			}
		).insert()

	def _create_ledger_clerk(self, role_name: str) -> str:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
		add_permission("Ledger Entry", role_name, 0)
		update_permission_property("Ledger Entry", role_name, 0, "create", 1)
		update_permission_property("Ledger Entry", role_name, 0, "write", 1)
		update_permission_property("Ledger Entry", role_name, 0, "submit", 1)
		add_permission("Ledger Account", role_name, 0)

		email = f"clerk-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Ledger Clerk",
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": role_name}],
			}
		).insert(ignore_permissions=True)
		return email

	def test_row_level_permissions_get_list_vs_get_all_vs_get_doc(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")

		role_name = f"Ledger Clerk {frappe.generate_hash(length=4)}"
		user_a = self._create_ledger_clerk(role_name)
		user_b = self._create_ledger_clerk(role_name)

		self.addCleanup(frappe.set_user, "Administrator")

		frappe.set_user(user_a)
		entry_a = self._make_entry(cash, rev).name

		frappe.set_user(user_b)
		entry_b = self._make_entry(cash, rev).name

		# get_list applies permission_query_conditions; get_all bypasses permissions
		visible_to_b = frappe.get_list("Ledger Entry", filters={"name": ["in", [entry_a, entry_b]]}, pluck="name")
		all_entries = frappe.get_all("Ledger Entry", filters={"name": ["in", [entry_a, entry_b]]}, pluck="name")

		self.assertEqual(visible_to_b, [entry_b])
		self.assertCountEqual(all_entries, [entry_a, entry_b])

		# Direct get_doc must also be blocked by has_permission hook
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Ledger Entry", entry_a).check_permission("read")

	def test_site_cache_hit_and_invalidation_on_submit(self):
		invalidate_trial_balance_cache()
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")

		# First call populates Redis + local cache
		tb_before = get_trial_balance(account_type="Asset")
		before_map = {r["name"]: r["balance"] for r in tb_before["accounts"]}
		self.assertEqual(before_map[cash], 0.0)
		redis_key = frappe.cache.make_key(trial_balance_cache_key("Asset"))
		self.assertIsNotNone(frappe.cache.get(redis_key))

		# Submitting a Ledger Entry must invalidate trial balance cache via doc_events
		entry = self._make_entry(cash, rev, amount=333.0)
		entry.submit()

		self.assertIsNone(frappe.cache.get(redis_key))

		tb_after = get_trial_balance(account_type="Asset")
		after_map = {r["name"]: r["balance"] for r in tb_after["accounts"]}
		self.assertEqual(after_map[cash], 333.0)

	def test_patch_idempotency_and_daily_integrity_task(self):
		cash = self._make_account("CASH", "Asset")
		rev = self._make_account("REV", "Revenue")
		entry = self._make_entry(cash, rev, amount=50.0)
		entry.submit()

		# Simulate legacy row with blank department, then run patch twice
		frappe.db.set_value("Ledger Entry", entry.name, "department", "")
		run_department_patch()
		run_department_patch()
		self.assertEqual(frappe.db.get_value("Ledger Entry", entry.name, "department"), "General")

		# Daily reconciliation should report no unbalanced submitted entries
		self.assertEqual(verify_ledger_integrity(), [])
