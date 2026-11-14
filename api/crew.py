"""RFID cards from contracts/README.md. Unknown cards remain valid inputs.

Names and roles are not assigned yet (firmware/FORMATO_JSON_BACKEND.md):
edit them here when the crew is known.
"""
CREW = {
    "F3786E09": {"name": "Crew member 1", "role": None},
    "336F8312": {"name": "Crew member 2", "role": None},
}


def profile(crew_id):
    known = CREW.get(crew_id)
    return {"crew_id": crew_id, "name": known["name"] if known else f"Unassigned · {crew_id}",
            "role": known["role"] if known else None, "assigned": known is not None}
