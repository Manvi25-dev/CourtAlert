import os

from dotenv import load_dotenv
from twilio.rest import Client


# Put TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env (project root).
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

    try:
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            body=message,
        )
        return msg.sid
    except Exception as exc:
        print(f"Twilio send failed: {exc}")
        raise


if __name__ == "__main__":
    # Run with: python whatsapp_send_demo.py
    demo_to_number = "+919540098192"
    demo_message = (
        "⚖️ CourtAlert\n\n"
        "Case: Demo vs State\n"
        "Court: Delhi High Court, Courtroom 3\n"
        "Time: Tomorrow 10:30 AM\n\n"
        "⚠️ Reach 30 mins early. Matter likely in first half."
    )

    try:
        message_sid = send_whatsapp(demo_to_number, demo_message)
        print(f"Message sent successfully. SID: {message_sid}")
    except Exception as exc:
        print(f"Error: {exc}")
