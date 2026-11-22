import frappe

TRIAL_BALANCE_PREFIX = "lab_core:trial_balance:"


def trial_balance_cache_key(account_type: str | None = None) -> str:
	return f"{TRIAL_BALANCE_PREFIX}{account_type or 'ALL'}"


def invalidate_trial_balance_cache(doc=None, method: str | None = None) -> None:
	"""Clear site-scoped trial balance entries from both L1 local cache and Redis."""
	frappe.cache.delete_keys(TRIAL_BALANCE_PREFIX)
