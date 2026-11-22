import json

import frappe
from frappe.utils import flt


def enqueue_submit_audit(doc, method: str | None = None) -> None:
	_enqueue_ledger_audit(doc.name, "Submit")


def enqueue_cancel_audit(doc, method: str | None = None) -> None:
	_enqueue_ledger_audit(doc.name, "Cancel")


def _enqueue_ledger_audit(entry_name: str, event_type: str) -> None:
	"""Schedule audit logging strictly after DB commit so the worker sees committed rows."""
	idempotency_key = f"{entry_name}:{event_type}"
	frappe.enqueue(
		"lab_core.ledger.audit.record_ledger_audit",
		queue="short",
		enqueue_after_commit=True,
		job_id=idempotency_key,
		deduplicate=True,
		entry_name=entry_name,
		event_type=event_type,
		idempotency_key=idempotency_key,
		triggered_by=frappe.session.user,
	)


def record_ledger_audit(
	entry_name: str,
	event_type: str,
	idempotency_key: str,
	triggered_by: str | None = None,
) -> str | None:
	"""Idempotently persist an audit snapshot for a committed Ledger Entry transition."""
	if frappe.db.exists("Ledger Audit Log", {"idempotency_key": idempotency_key}):
		return None

	entry = frappe.get_doc("Ledger Entry", entry_name)
	total_debit = sum(flt(line.amount) for line in entry.lines if line.direction == "Debit")
	payload = {
		"posting_date": str(entry.posting_date),
		"reference_no": entry.reference_no,
		"docstatus": entry.docstatus,
		"lines": [
			{"account": line.account, "direction": line.direction, "amount": flt(line.amount)}
			for line in entry.lines
		],
	}

	audit = frappe.get_doc(
		{
			"doctype": "Ledger Audit Log",
			"idempotency_key": idempotency_key,
			"ledger_entry": entry.name,
			"event_type": event_type,
			"total_amount": total_debit,
			"recorded_by": triggered_by or frappe.session.user,
			"payload_json": json.dumps(payload, sort_keys=True),
		}
	)
	audit.insert(ignore_permissions=True)
	return audit.name
