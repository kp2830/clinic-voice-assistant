"""In-memory mock data for the clinic support demo.

There is no database and no external API. Every patient ID "exists": the
first time we see one, we mint a patient with a standard bundle of visit
credits and one upcoming appointment. Tool side effects (booking, cancelling)
mutate this in-process dict so a single session behaves consistently — restart
the server and it resets.
"""

from __future__ import annotations

from copy import deepcopy

# Visit credits a fresh patient starts with, by visit type.
_DEFAULT_CREDITS: dict[str, int] = {
    "general_consult": 4,  # one credit is already spent on the seeded appointment
    "specialist_consult": 2,
    "lab_test": 3,
}

# The (fake) appointment slots. `credit_type` is what booking a slot spends.
SLOT_SCHEDULE: list[dict[str, str]] = [
    {"id": "gp-mon", "name": "General Consultation (Dr. Mehta)", "time": "Mon 10:00 AM", "credit_type": "general_consult"},
    {"id": "derm-tue", "name": "Dermatology (Dr. Rao)", "time": "Tue 4:30 PM", "credit_type": "specialist_consult"},
    {"id": "ortho-wed", "name": "Orthopaedics (Dr. Singh)", "time": "Wed 11:00 AM", "credit_type": "specialist_consult"},
    {"id": "lab-thu", "name": "Blood Test Panel", "time": "Thu 8:00 AM", "credit_type": "lab_test"},
    {"id": "gp-sat", "name": "General Consultation (Dr. Iyer)", "time": "Sat 9:30 AM", "credit_type": "general_consult"},
]

# patient_id -> patient record. Populated lazily by get_patient().
_PATIENTS: dict[str, dict] = {}


def get_patient(patient_id: str) -> dict:
    """Return the patient for this ID, minting one on first sight.

    Regardless of the ID provided, this always "finds" a patient — the demo
    has no real lookup to fail. New patients start with one upcoming
    appointment so there is always something to cancel or reschedule.
    """
    key = (patient_id or "guest").strip()
    if key not in _PATIENTS:
        _PATIENTS[key] = {
            "patient_id": key,
            "name": "Alex Patient",
            "plan": "Family Health Plan",
            "status": "active",
            "credits": deepcopy(_DEFAULT_CREDITS),
            "appointments": [
                {
                    "slot": "General Consultation (Dr. Mehta)",
                    "time": "Mon 10:00 AM",
                    "date": "next Monday",
                    "credit_type": "general_consult",
                }
            ],
        }
    return _PATIENTS[key]


def cancel_appointment(patient_id: str, slot_query: str = "") -> dict:
    """Cancel an upcoming appointment and refund its credit.

    With no `slot_query`, cancels the most recent appointment. Returns
    {"ok": bool, "reason"?: str, "appointment"?: dict, "patient": <record>}.
    """
    patient = get_patient(patient_id)
    q = (slot_query or "").strip().lower()
    for appt in reversed(patient["appointments"]):
        if not q or q in appt["slot"].lower() or q in appt["time"].lower():
            patient["appointments"].remove(appt)
            patient["credits"][appt["credit_type"]] += 1
            return {"ok": True, "appointment": appt, "patient": patient}
    return {"ok": False, "reason": "no matching upcoming appointment", "patient": patient}


def find_slot(slot_query: str) -> dict | None:
    """Best-effort match of a slot by id, name, or time substring."""
    q = (slot_query or "").strip().lower()
    if not q:
        return None
    for slot in SLOT_SCHEDULE:
        if q in slot["id"].lower() or q in slot["name"].lower() or q in slot["time"].lower():
            return slot
    return None


def book_appointment(patient_id: str, slot: dict, date: str) -> dict:
    """Spend one credit of the slot's type and record the appointment.

    Returns a result dict: {"ok": bool, "reason"?: str, "patient": <record>}.
    """
    patient = get_patient(patient_id)
    credit_type = slot["credit_type"]
    remaining = patient["credits"].get(credit_type, 0)
    if remaining <= 0:
        return {"ok": False, "reason": f"no {credit_type.replace('_', ' ')} credits left", "patient": patient}
    patient["credits"][credit_type] = remaining - 1
    patient["appointments"].append(
        {"slot": slot["name"], "time": slot["time"], "date": date, "credit_type": credit_type}
    )
    return {"ok": True, "patient": patient}
