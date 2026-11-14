"""RFID cards from contracts/README.md. Unknown cards remain valid inputs."""
CREW = {
    "F3786E09": {"name": "Crew member 1", "role": "Commander"},
    "336F8312": {"name": "Crew member 2", "role": "Medical officer"},
}


def profile(crew_id):
    known = CREW.get(crew_id)
    return {"crew_id": crew_id, "name": known["name"] if known else f"Unassigned · {crew_id}",
            "role": known["role"] if known else None, "assigned": known is not None}
