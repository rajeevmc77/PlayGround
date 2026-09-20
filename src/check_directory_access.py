#!/usr/bin/env python3
"""
Check whether rajeev.mc@aot-technologies.com can list all names/email
addresses of users in the aot-technologies.com Google Workspace domain.

It tries two paths and reports which one (if any) actually works for
this account:

  1. People API  -> listDirectoryPeople   (works for a regular user if
     the Workspace admin has enabled "Global Directory" sharing)
  2. Admin SDK   -> Directory API users.list  (requires the signed-in
     account to have Workspace admin/delegated rights)

Setup (one-time):
  1. Create/select a project in Google Cloud Console:
     https://console.cloud.google.com/
  2. Enable both APIs on that project:
       - People API
       - Admin SDK API
  3. Create an OAuth 2.0 Client ID of type "Desktop app" and download
     it as credentials.json into the project root (one level up from
     this script, in src/).
  4. pip install -r requirements.txt
  5. Run (from the project root): python src/check_directory_access.py
     A browser window opens - sign in as rajeev.mc@aot-technologies.com
     and grant the requested scopes.

The first successful run caches a token in token.json so future runs
don't need the browser again (until it expires/is revoked).
"""

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

EXPECTED_USER = "rajeev.mc@aot-technologies.com"
DOMAIN = "aot-technologies.com"

# credentials.json/token.json live in the project root, one level up from
# this script's own location (src/) - anchored to the file's path rather
# than the current working directory, so this still works run from
# anywhere, e.g. `python src/check_directory_access.py` from the root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = str(PROJECT_ROOT / "credentials.json")
TOKEN_FILE = str(PROJECT_ROOT / "token.json")

# Request both scopes up front so one sign-in covers both checks.
SCOPES = [
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def get_credentials() -> Credentials:
    if not os.path.exists(CREDENTIALS_FILE):
        sys.exit(
            f"Missing {CREDENTIALS_FILE}. Download an OAuth 2.0 Desktop "
            f"app client ID from Google Cloud Console and save it here."
        )

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


def confirm_signed_in_user(creds: Credentials) -> str:
    oauth2 = build("oauth2", "v2", credentials=creds)
    info = oauth2.userinfo().get().execute()
    email = info.get("email", "<unknown>")
    if email.lower() != EXPECTED_USER.lower():
        print(
            f"WARNING: signed in as {email}, not {EXPECTED_USER}. "
            f"Delete {TOKEN_FILE} and re-run to switch accounts.\n"
        )
    return email


def check_people_api(creds: Credentials):
    """Regular-user path: People API directory listing."""
    service = build("people", "v1", credentials=creds)
    all_users = []
    page_token = None

    try:
        while True:
            results = (
                service.people()
                .listDirectoryPeople(
                    readMask="names,emailAddresses",
                    sources="DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )

            for person in results.get("people", []):
                names = person.get("names", [{}])
                display_name = names[0].get("displayName", "No Name") if names else "No Name"
                emails = [e.get("value") for e in person.get("emailAddresses", [])]
                all_users.append({"name": display_name, "emails": emails})

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return True, all_users, None

    except HttpError as e:
        return False, [], e


def check_admin_sdk(creds: Credentials):
    """Admin path: Admin SDK Directory API users.list."""
    service = build("admin", "directory_v1", credentials=creds)
    all_users = []
    page_token = None

    try:
        while True:
            results = (
                service.users()
                .list(
                    domain=DOMAIN,
                    maxResults=500,
                    orderBy="email",
                    pageToken=page_token,
                )
                .execute()
            )

            for user in results.get("users", []):
                full_name = user.get("name", {}).get("fullName", "No Name")
                primary_email = user.get("primaryEmail")
                all_users.append({"name": full_name, "emails": [primary_email]})

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        return True, all_users, None

    except HttpError as e:
        return False, [], e


def print_report(label: str, ok: bool, users, error):
    print(f"\n=== {label} ===")
    if ok:
        print(f"ACCESS GRANTED — retrieved {len(users)} directory entr{'y' if len(users) == 1 else 'ies'}.")
    else:
        status = getattr(error, "status_code", None) or getattr(error.resp, "status", "?")
        print(f"ACCESS DENIED (HTTP {status})")
        print(f"Reason: {error}")


def print_users(users):
    print(f"\nName{' ' * 36}Email(s)")
    print("-" * 70)
    for u in sorted(users, key=lambda x: x["name"].lower()):
        print(f"{u['name']:<40}{', '.join(u['emails'])}")


def main():
    creds = get_credentials()
    signed_in_as = confirm_signed_in_user(creds)
    print(f"Signed in as: {signed_in_as}")
    print(f"Checking directory-listing access for domain: {DOMAIN}\n")

    people_ok, people_users, people_err = check_people_api(creds)
    print_report("Option 1: People API (listDirectoryPeople) — regular user path", people_ok, people_users, people_err)

    admin_ok, admin_users, admin_err = check_admin_sdk(creds)
    print_report("Option 2: Admin SDK Directory API (users.list) — admin path", admin_ok, admin_users, admin_err)

    print("\n=== Summary ===")
    if people_ok or admin_ok:
        print(f"{EXPECTED_USER} CAN retrieve the full list of names/emails in {DOMAIN}.")
        source = "People API" if people_ok else "Admin SDK"
        print(f"(via {source})")
        print_users(people_users if people_ok else admin_users)
    else:
        print(f"{EXPECTED_USER} CANNOT currently retrieve the directory list via either API.")
        print("Likely causes: Global Directory sharing is off for regular users, and this")
        print("account does not hold Workspace admin / delegated admin rights.")


if __name__ == "__main__":
    main()
