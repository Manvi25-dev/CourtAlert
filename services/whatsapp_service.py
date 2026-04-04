import os

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

# Load .env values for local/dev execution.
load_dotenv()

TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14783128194")


def send_whatsapp(to_number: str, message: str) -> str:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        raise RuntimeError(
            "Missing Twilio credentials. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env"
        )

    client = Client(account_sid, auth_token)
    to_value = to_number.strip()
    if not to_value.startswith("whatsapp:"):
        to_value = f"whatsapp:{to_value}"

    try:
        twilio_message = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_value,
            body=message,
        )
        return twilio_message.sid
    except TwilioRestException as exc:
        raise RuntimeError(f"Twilio send failed: {exc.msg}") from exc
    except Exception as exc:
        raise RuntimeError(f"WhatsApp send failed: {exc}") from exc
