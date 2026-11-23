"""Microsoft Graph access with an Entra ID app registration (client-credentials flow).

Permissions to request from IT (application permissions, admin consent):
  Mail.Send       - limited with an Exchange application access policy to the
                    sender mailbox (MAIL_SENDER) only
  Sites.Selected  - granted read access to the one SharePoint site that holds
                    the reference folder
"""
import threading

import msal
import requests

from . import config

GRAPH = "https://graph.microsoft.com/v1.0"
_app = None
_lock = threading.Lock()


def token():
    global _app
    with _lock:
        if _app is None:
            _app = msal.ConfidentialClientApplication(
                config.GRAPH_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{config.GRAPH_TENANT_ID}",
                client_credential=config.GRAPH_CLIENT_SECRET,
            )
        res = _app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in res:
        raise RuntimeError(f"Microsoft Graph sign-in failed: {res.get('error')}: {res.get('error_description')}")
    return res["access_token"]


def get(path, **kw):
    r = requests.get(GRAPH + path if path.startswith("/") else path,
                     headers={"Authorization": f"Bearer {token()}"}, timeout=60, **kw)
    r.raise_for_status()
    return r


def post(path, json_body):
    r = requests.post(GRAPH + path, json=json_body,
                      headers={"Authorization": f"Bearer {token()}"}, timeout=60)
    r.raise_for_status()
    return r
