"""Send the sign-in code."""
import logging
from urllib.parse import quote

from . import config

log = logging.getLogger("bidapp.mail")


def send_code(email, code):
    subject = f"{config.APP_NAME} sign-in code: {code}"
    body = (f"Your sign-in code is {code}.\n\n"
            f"It expires in {config.OTP_TTL_MIN} minutes and works once. "
            "If you did not try to sign in, ignore this email and tell IT Security.\n\n"
            "VITRO Data Centers - internal tool")
    if config.MAIL_MODE == "console":
        log.warning("DEV MODE sign-in code for %s: %s", email, code)
        return
    from . import graph

    graph.post(f"/users/{quote(config.MAIL_SENDER)}/sendMail", {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": email}}],
        },
        "saveToSentItems": False,
    })
