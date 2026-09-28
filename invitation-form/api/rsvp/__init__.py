"""Receives an RSVP from the form and saves it as a row in Azure Table Storage."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.data.tables import TableClient

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_GUESTS = 10

_table = None


def get_table() -> TableClient:
    """Create the table client once and reuse it between requests."""
    global _table
    if _table is None:
        _table = TableClient.from_connection_string(
            os.environ["STORAGE_CONNECTION_STRING"],
            table_name=os.environ.get("TABLE_NAME", "Rsvp"),
        )
    return _table


def respond(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
    )


def text(data: dict, key: str, max_len: int) -> str:
    return str(data.get(key) or "").strip()[:max_len]


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except ValueError:
        return respond(400, {"error": "Skjemaet ble sendt i feil format. Last inn siden på nytt og prøv igjen."})
    if not isinstance(data, dict):
        return respond(400, {"error": "Skjemaet ble sendt i feil format. Last inn siden på nytt og prøv igjen."})

    # Honeypot: real people never see this field, spam bots fill it in.
    # Pretend it worked so the bot doesn't try again.
    if data.get("website"):
        return respond(200, {"ok": True})

    name = text(data, "name", 100)
    email = text(data, "email", 254)
    allergies = text(data, "allergies", 500)
    message = text(data, "message", 1000)
    attending = data.get("attending")

    if not name:
        return respond(400, {"error": "Skriv inn navnet ditt."})
    if email and not EMAIL_RE.match(email):
        return respond(400, {"error": "E-postadressen ser ikke riktig ut. Sjekk den, eller la feltet stå tomt."})
    if attending not in (True, False):
        return respond(400, {"error": "Velg om du kommer eller ikke."})

    if attending:
        try:
            guests = int(data.get("guests", 1))
        except (TypeError, ValueError):
            return respond(400, {"error": "Antall personer må være et tall."})
        if not 1 <= guests <= MAX_GUESTS:
            return respond(400, {"error": f"Antall personer må være mellom 1 og {MAX_GUESTS}."})
    else:
        guests = 0

    entity = {
        "PartitionKey": "rsvp",
        "RowKey": uuid.uuid4().hex,
        "Name": name,
        "Email": email,
        "Attending": attending,
        "Guests": guests,
        "Allergies": allergies,
        "Message": message,
        "SubmittedAt": datetime.now(timezone.utc),
    }

    try:
        get_table().create_entity(entity)
    except Exception:
        logging.exception("Could not save RSVP")
        return respond(500, {"error": "Svaret ble ikke lagret på grunn av en feil hos oss. Prøv igjen om litt."})

    return respond(200, {"ok": True})
