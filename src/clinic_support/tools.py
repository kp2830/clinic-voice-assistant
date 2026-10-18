"""Tools for the clinic support agents.

Two kinds live here:

* **Business tools** (`check_credits`, `cancel_appointment`, `list_slots`,
  `book_appointment`) — the things specialists actually do. They hit the mock data
  store and return plain strings.
* **Handoff tools** (`transfer_to_*`) — the mechanism that moves control
  between agent nodes. Each returns a ``Command`` that updates ``active_agent``
  and jumps to another node in the *parent* graph via ``graph=Command.PARENT``.

The handoff tools follow the LangChain "multiple agent subgraphs" pattern: they
forward the AIMessage that triggered the handoff plus a ToolMessage closing the
tool call, so the receiving agent sees a valid, minimal conversation history.
"""

from __future__ import annotations

from langchain.messages import AIMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from . import mock_data

# --- Business tools ---------------------------------------------------------


@tool
def check_credits(patient_id: str) -> str:
    """Look up how many visit credits remain on a patient's plan, by visit type."""
    patient = mock_data.get_patient(patient_id)
    lines = [f"- {ctype.replace('_', ' ')}: {n}" for ctype, n in patient["credits"].items()]
    return (
        f"Patient {patient['patient_id']} ({patient['plan']}, "
        f"status: {patient['status']}) has these visit credits left:\n" + "\n".join(lines)
    )


@tool
def cancel_appointment(patient_id: str, appointment: str = "") -> str:
    """Cancel an upcoming appointment and refund its visit credit.

    `appointment` is an optional doctor, visit type, or time to match; leave it
    empty to cancel the patient's most recent appointment.
    """
    result = mock_data.cancel_appointment(patient_id, appointment)
    if not result["ok"]:
        return f"Couldn't cancel: {result['reason']}."
    appt = result["appointment"]
    credit_type = appt["credit_type"]
    left = result["patient"]["credits"][credit_type]
    return (
        f"Cancelled {appt['slot']} ({appt['time']}, {appt['date']}). "
        f"The visit credit was refunded — {left} {credit_type.replace('_', ' ')} credit(s) now available."
    )


@tool
def list_slots() -> str:
    """List the appointment slots available to book this week."""
    lines = [
        f"- {s['name']} ({s['time']}) — costs 1 {s['credit_type'].replace('_', ' ')} credit"
        for s in mock_data.SLOT_SCHEDULE
    ]
    return "Available appointments:\n" + "\n".join(lines)


@tool
def book_appointment(patient_id: str, slot_name: str, date: str) -> str:
    """Book an appointment for a patient on a given date. Spends one credit.

    `date` is the day the patient wants to come in (e.g. "2026-06-20" or
    "next Monday") — ask the patient for it before calling this tool.
    """
    slot = mock_data.find_slot(slot_name)
    if slot is None:
        return (
            f"Couldn't find an appointment matching '{slot_name}'. "
            "Use list_slots to see what's available."
        )
    result = mock_data.book_appointment(patient_id, slot, date)
    if not result["ok"]:
        return f"Couldn't book {slot['name']}: {result['reason']}."
    patient = result["patient"]
    remaining = patient["credits"][slot["credit_type"]]
    return (
        f"Booked {slot['name']} ({slot['time']}) for {date}. "
        f"You have {remaining} {slot['credit_type'].replace('_', ' ')} credit(s) left."
    )


# --- Handoff tools ----------------------------------------------------------


def _handoff(goto: str, runtime: ToolRuntime, note: str) -> Command:
    """Build a Command that transfers control to another agent node.

    Passes only the triggering AIMessage and a closing ToolMessage to the
    parent graph — not the whole sub-agent history — so the receiving agent
    gets valid, focused context.
    """
    last_ai = next(
        msg for msg in reversed(runtime.state["messages"]) if isinstance(msg, AIMessage)
    )
    transfer_message = ToolMessage(content=note, tool_call_id=runtime.tool_call_id)
    return Command(
        goto=goto,
        update={"active_agent": goto, "messages": [last_ai, transfer_message]},
        graph=Command.PARENT,
    )


@tool
def transfer_to_cancellation(runtime: ToolRuntime) -> Command:
    """Transfer the patient to the appointment cancellation specialist."""
    return _handoff("cancellation", runtime, "Transferred to cancellation specialist.")


@tool
def transfer_to_credits(runtime: ToolRuntime) -> Command:
    """Transfer the patient to the visit-credits specialist."""
    return _handoff("credits", runtime, "Transferred to credits specialist.")


@tool
def transfer_to_booking(runtime: ToolRuntime) -> Command:
    """Transfer the patient to the appointment booking specialist."""
    return _handoff("booking", runtime, "Transferred to booking specialist.")


@tool
def transfer_to_triage(runtime: ToolRuntime) -> Command:
    """Hand the patient back to the front desk to be re-routed."""
    return _handoff("triage", runtime, "Transferred back to the front desk.")
