"""Create the single account via the Supabase Admin API (no dashboard clicks).

Works against local OR cloud — just point the env at the right URL/key.

    SUPABASE_URL=http://127.0.0.1:54321 \
    SERVICE_KEY=<service_role key> \
    MY_EMAIL=me@example.com MY_PASSWORD=secret \
    python setup/create_user.py
"""
import os
import requests

url = os.environ["SUPABASE_URL"].rstrip("/")
key = os.environ["SERVICE_KEY"]

r = requests.post(
    f"{url}/auth/v1/admin/users",
    headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    },
    json={
        "email": os.environ["MY_EMAIL"],
        "password": os.environ["MY_PASSWORD"],
        "email_confirm": True,
    },
    timeout=30,
)
print(r.status_code, r.text)
# 422 "email_exists" is fine on re-runs; only raise on other errors.
if r.status_code >= 300 and "already" not in r.text.lower() and "exists" not in r.text.lower():
    r.raise_for_status()
