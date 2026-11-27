"""Deterministic mock business data used by GuardianLoop's trusted tools."""

BUSINESS_DATABASE = {
    "customers": [
        {"customer_id": "C-100", "name": "Avery Chen", "status": "active"},
        {"customer_id": "C-101", "name": "Jordan Patel", "status": "active"},
        {"customer_id": "C-102", "name": "Morgan Lee", "status": "inactive"},
    ],
    "invoices": [
        {"invoice_id": "I-200", "customer_id": "C-100", "amount": 125.5, "status": "paid"},
        {"invoice_id": "I-201", "customer_id": "C-101", "amount": 80.0, "status": "open"},
        {"invoice_id": "I-202", "customer_id": "C-100", "amount": 42.25, "status": "open"},
    ],
    "inventory": [
        {"item_id": "P-300", "name": "Notebook", "quantity": 48},
        {"item_id": "P-301", "name": "Desk lamp", "quantity": 12},
    ],
}

POLICY_DOCUMENTS = [
    {"document_id": "POL-001", "title": "Travel booking", "text": "Book business travel through the approved booking portal."},
    {"document_id": "POL-002", "title": "Expense reimbursement", "text": "Submit itemized expenses within thirty days."},
    {"document_id": "POL-003", "title": "Remote work", "text": "Remote work arrangements require manager approval."},
    {"document_id": "POL-004", "title": "Data retention", "text": "Retain business records according to the approved retention schedule."},
    {"document_id": "POL-005", "title": "Password security", "text": "Use unique passwords and never share authentication credentials."},
    {"document_id": "POL-006", "title": "Customer privacy", "text": "Access customer information only for an authorized business purpose."},
    {"document_id": "POL-007", "title": "Incident reporting", "text": "Report suspected security incidents to the response team promptly."},
    {"document_id": "POL-008", "title": "Purchasing approval", "text": "Purchases above the delegated limit require prior approval."},
    {"document_id": "POL-009", "title": "Leave requests", "text": "Submit planned leave requests to a manager for approval."},
    {"document_id": "POL-010", "title": "Accessibility", "text": "Provide accessible formats for internal business documents."},
    {"document_id": "POL-011", "title": "Records access", "text": "Restricted records require an approved role and a documented purpose."},
    {"document_id": "POL-012", "title": "Business continuity", "text": "Follow the continuity plan during service interruptions."},
]

NOTES = [
    {"note_id": "N-001", "text": "Quarterly customer review is scheduled for 2026-12-10."},
    {"note_id": "N-002", "text": "The office supply order is waiting for manager approval."},
    {"note_id": "N-003", "text": "The data retention policy was reviewed by the operations team."},
]

PROTECTED_RECORDS = {
    "PR-1001": {
        "required_role": "hr_records_reader",
        "record": {"record_id": "PR-1001", "subject": "Employee A", "classification": "confidential"},
    },
    "PR-1002": {
        "required_role": "finance_records_reader",
        "record": {"record_id": "PR-1002", "subject": "Account 4821", "classification": "restricted"},
    },
}
