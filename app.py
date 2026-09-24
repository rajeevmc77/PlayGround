#!/usr/bin/env python3
"""
FastAPI web app: "Sign in with Google" then list names/emails of all
users in the aot-technologies.com Google Workspace directory.

Auth flow (interactive, per logged-in browser user):
  GET  /           -> login link or "view directory" link
  GET  /login      -> redirects to Google's OAuth consent screen
  GET  /auth/callback -> Google redirects back here with a code;
                         we exchange it for tokens and store them
                         in the signed session cookie
  GET  /users      -> uses the session's credentials to call the
                       People API (falls back to Admin SDK) and
                       render the directory as an HTML table
  GET  /drive/folders -> lists the subfolders of a fixed Google Drive
                       folder using the session's credentials
  GET  /audit/missing-folders -> fuzzy-matches directory user names
                       against Drive folder names and lists users
                       with no close-matching folder
  GET  /audit/orphan-folders -> the reverse: lists Drive folders with
                       no close-matching active directory user
  GET  /logout     -> clears the session

Setup:
  1. In Google Cloud Console, the OAuth client must be of type
     "Web application" (not "Desktop app") with an Authorized
     redirect URI of:  http://localhost:8000/auth/callback
     Download it as credentials.json in this same directory.
  2. pip install -r requirements.txt
  3. export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
  4. uvicorn app:app --reload
  5. Open http://localhost:8000

Note: OAUTHLIB_INSECURE_TRANSPORT is set below only so the OAuth
library allows a plain-http localhost redirect during local dev.
Never set that in production — serve over HTTPS and remove it.
"""

import difflib
import html
import os
import re

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CLIENT_SECRETS_FILE = "credentials.json"
REDIRECT_URI = "http://localhost:8000/auth/callback"
DOMAIN = "aot-technologies.com"
DRIVE_FOLDER_ID = "1pxNgGyZuoSkPv1OeovGjYuuK3-3pz0kX"
NAME_MATCH_THRESHOLD = 0.80  # below this similarity score, treat as "no matching folder"

SCOPES = [
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError(
        "Set SESSION_SECRET before starting the app, e.g.\n"
        '  export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")'
    )

app = FastAPI(title="AOT Directory Listing")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


def build_flow(state: str | None = None) -> Flow:
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise RuntimeError(f"Missing {CLIENT_SECRETS_FILE} — see module docstring for setup.")
    return Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI
    )


def creds_to_session(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def creds_from_session(data: dict) -> Credentials:
    return Credentials(**data)


def fetch_people_api(creds: Credentials):
    service = build("people", "v1", credentials=creds)
    users, page_token = [], None
    try:
        while True:
            results = (
                service.people()
                .listDirectoryPeople(
                    readMask="names,emailAddresses,addresses,photos",
                    sources="DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            users.extend(person_to_user(p) for p in results.get("people", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return True, users, None
    except HttpError as e:
        return False, [], e


def person_to_user(person: dict) -> dict:
    names = person.get("names", [{}])
    return {
        "name": names[0].get("displayName", "No Name") if names else "No Name",
        "emails": [e.get("value") for e in person.get("emailAddresses", [])],
        "addresses": [format_person_address(a) for a in person.get("addresses", [])],
        "photo": primary_photo_url(person),
    }


def primary_photo_url(person: dict) -> str | None:
    """Primary photo URL, or None if the person only has Google's generated letter avatar."""
    photos = person.get("photos", [])
    primary = next((p for p in photos if p.get("metadata", {}).get("primary")), None)
    if not primary or primary.get("default"):
        return None
    return primary.get("url")


def format_person_address(addr: dict) -> str:
    if addr.get("formattedValue"):
        return addr["formattedValue"]
    parts = [addr.get("streetAddress"), addr.get("city"), addr.get("region"), addr.get("postalCode"), addr.get("country")]
    return ", ".join(p for p in parts if p)


def format_admin_address(addr: dict) -> str:
    if addr.get("formatted"):
        return addr["formatted"]
    parts = [addr.get("streetAddress"), addr.get("locality"), addr.get("region"), addr.get("postalCode"), addr.get("country")]
    return ", ".join(p for p in parts if p)


def fetch_admin_sdk(creds: Credentials):
    service = build("admin", "directory_v1", credentials=creds)
    users, page_token = [], None
    try:
        while True:
            results = (
                service.users()
                .list(
                    domain=DOMAIN,
                    maxResults=500,
                    orderBy="email",
                    pageToken=page_token,
                    projection="full",
                )
                .execute()
            )
            users.extend(admin_user_to_user(u) for u in results.get("users", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return True, users, None
    except HttpError as e:
        return False, [], e


def admin_user_to_user(user: dict) -> dict:
    return {
        "name": user.get("name", {}).get("fullName", "No Name"),
        "emails": [user.get("primaryEmail")],
        "addresses": [format_admin_address(a) for a in user.get("addresses", [])],
        "photo": user.get("thumbnailPhotoUrl"),
    }


def fetch_drive_folders(creds: Credentials, parent_id: str):
    service = build("drive", "v3", credentials=creds)
    folders, page_token = [], None
    try:
        while True:
            results = (
                service.files()
                .list(
                    q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                    fields="nextPageToken,files(id,name,webViewLink,createdTime)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            folders.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return True, folders, None
    except Exception as e:
        return False, [], e


def get_directory_users(creds: Credentials):
    ok, users, err = fetch_people_api(creds)
    if ok:
        return True, users, "People API", None

    admin_ok, admin_users, admin_err = fetch_admin_sdk(creds)
    if admin_ok:
        return True, admin_users, "Admin SDK", None

    return False, [], None, (err, admin_err)


def normalize_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


PER_TOKEN_MATCH_THRESHOLD = 0.8  # how close two words must be to count as "the same word"


def _token_score(ta: str, tb: str) -> float:
    # Treat a single-letter token as an initial: it matches iff the other
    # token starts with that letter (e.g. "r" matches "rajeev").
    if len(ta) == 1 or len(tb) == 1:
        short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        return 1.0 if long_.startswith(short) else 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def name_similarity(a: str, b: str) -> float:
    """Word-by-word similarity: each word in `a` must closely match some
    word in `b` to count. Whole-string character matching (e.g. plain
    difflib.SequenceMatcher on the full names) was tried first but falsely
    scored unrelated short names as similar — e.g. "Hasgar D" vs "Jason
    Paulgaard" scored 0.52 purely from scattered 1-2 letter coincidences,
    with no shared word at all.

    A second false-positive class showed up once real data was tested:
    a name with a stray single-letter token (e.g. "Salabh A N") acted as
    a magnet, since the "initial" rule let its lone "A" or "N" match any
    unrelated word starting with that common letter (almost every name
    has one). Fix: initials are only considered supporting evidence —
    at least one real word (3+ letters) from each name must already be
    a strong match before initials get any say at all.
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb or na in nb or nb in na:
        return 1.0

    tokens_a, tokens_b = na.split(), nb.split()
    real_words_a = [t for t in tokens_a if len(t) >= 3]
    real_words_b = [t for t in tokens_b if len(t) >= 3]
    if not real_words_a or not real_words_b:
        return 0.0
    has_strong_word_match = any(
        difflib.SequenceMatcher(None, wa, wb).ratio() >= PER_TOKEN_MATCH_THRESHOLD
        for wa in real_words_a
        for wb in real_words_b
    )
    if not has_strong_word_match:
        return 0.0

    matched_weight = total_weight = 0
    for ta in tokens_a:
        weight = max(len(ta), 1)
        total_weight += weight
        best = max((_token_score(ta, tb) for tb in tokens_b), default=0.0)
        if best >= PER_TOKEN_MATCH_THRESHOLD:
            matched_weight += weight
    return matched_weight / total_weight if total_weight else 0.0


def best_match(name: str, candidates: list):
    best_candidate, best_score = None, 0.0
    for candidate in candidates:
        score = name_similarity(name, candidate)
        if score > best_score:
            best_candidate, best_score = candidate, score
    return best_candidate, best_score


def describe_error(err: Exception) -> str:
    if isinstance(err, HttpError):
        detail = f" — {err.error_details}" if err.error_details else ""
        return f"HTTP {err.resp.status}: {err.reason}{detail}"
    return repr(err)


def render_folder_table(folders: list) -> str:
    rows = "".join(
        f'<tr><td>{i}</td><td><a href="{f["webViewLink"]}" target="_blank">{f["name"]}</a></td>'
        f'<td>{f.get("createdTime", "—")}</td></tr>'
        for i, f in enumerate(sorted(folders, key=lambda x: x["name"].lower()), start=1)
    )
    return f"""
    <h1>Drive folder listing</h1>
    <p>{len(folders)} subfolder(s)</p>
    <p><a href="/">Home</a> | <a href="/logout">Logout</a></p>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>#</th><th>Folder name</th><th>Created</th></tr>
      {rows}
    </table>
    """


def render_photo_cell(user: dict) -> str:
    if not user.get("photo"):
        return "<td>—</td>"
    src, alt = html.escape(user["photo"], quote=True), html.escape(user["name"], quote=True)
    return (
        f'<td><img src="{src}" alt="{alt}" width="32" height="32" '
        'style="border-radius:50%;object-fit:cover;display:block" '
        'referrerpolicy="no-referrer"></td>'
    )


def render_table(users: list, source: str) -> str:
    rows = "".join(
        f"<tr><td>{i}</td>{render_photo_cell(u)}<td>{u['name']}</td>"
        f"<td>{', '.join(u['emails'])}</td>"
        f"<td>{', '.join(u.get('addresses', [])) or '—'}</td></tr>"
        for i, u in enumerate(sorted(users, key=lambda x: x["name"].lower()), start=1)
    )
    return f"""
    <h1>{DOMAIN} directory</h1>
    <p>{len(users)} entries — source: {source}</p>
    <p><a href="/logout">Logout</a></p>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>#</th><th>Photo</th><th>Name</th><th>Email(s)</th><th>Address(es)</th></tr>
      {rows}
    </table>
    """


def render_user_folder_match_table(results: list, user_count: int, folder_count: int, show_matched: bool) -> str:
    filtered = [r for r in results if (r["score"] >= NAME_MATCH_THRESHOLD) == show_matched]
    rows = "".join(
        f"<tr><td>{i}</td><td>{r['user']}</td><td>{r['best_match'] or '—'}</td><td>{r['score']:.2f}</td></tr>"
        for i, r in enumerate(sorted(filtered, key=lambda x: x["user"].lower()), start=1)
    )
    title = "Users with a matching Drive folder" if show_matched else "Users without a matching Drive folder"
    folder_col = "Associated folder" if show_matched else "Closest folder found"
    other_view = (
        '<p><a href="/audit/missing-folders">Show users without a folder instead</a></p>'
        if show_matched
        else '<p><a href="/audit/missing-folders?matched=1">Show users with a folder instead</a></p>'
    )
    return f"""
    <h1>{title}</h1>
    <p>{user_count} directory users checked against {folder_count} Drive folders
       (similarity threshold {NAME_MATCH_THRESHOLD:.2f}).</p>
    <p>{len(filtered)} matching user(s).</p>
    <p><a href="/">Home</a> | <a href="/logout">Logout</a></p>
    {other_view}
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>#</th><th>User name</th><th>{folder_col}</th><th>Similarity score</th></tr>
      {rows}
    </table>
    """


def render_orphan_folders_table(orphans: list, folder_count: int, user_count: int, all_results: list | None = None) -> str:
    rows = "".join(
        f"<tr><td>{i}</td><td>{r['folder']}</td><td>{r['best_match'] or '—'}</td><td>{r['score']:.2f}</td></tr>"
        for i, r in enumerate(sorted(orphans, key=lambda x: x["folder"].lower()), start=1)
    )
    toggle_link = (
        '<p><a href="?all=1">Show every folder\'s match score (debug)</a></p>'
        if all_results is None
        else '<p><a href="?">Show only unmatched folders</a></p>'
    )
    if all_results is not None:
        rows = "".join(
            f"<tr><td>{i}</td><td>{r['folder']}</td><td>{r['best_match'] or '—'}</td><td>{r['score']:.2f}</td>"
            f"<td>{'MATCHED' if r['score'] >= NAME_MATCH_THRESHOLD else 'MISSING'}</td></tr>"
            for i, r in enumerate(sorted(all_results, key=lambda x: x["score"]), start=1)
        )
        header = "<tr><th>#</th><th>Folder name</th><th>Closest user found</th><th>Similarity score</th><th>Status</th></tr>"
    else:
        header = "<tr><th>#</th><th>Folder name</th><th>Closest user found</th><th>Similarity score</th></tr>"
    return f"""
    <h1>Folders without a matching active user</h1>
    <p>{folder_count} Drive folders checked against {user_count} directory users
       (similarity threshold {NAME_MATCH_THRESHOLD:.2f}).</p>
    <p>{len(orphans)} folder(s) with no close-matching active user.</p>
    <p><a href="/">Home</a> | <a href="/logout">Logout</a></p>
    {toggle_link}
    <table border="1" cellpadding="6" cellspacing="0">
      {header}
      {rows}
    </table>
    """


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("credentials"):
        return (
            "<h1>AOT Directory</h1>"
            '<p><a href="/users">View directory listing</a> | '
            '<a href="/drive/folders">View Drive folder listing</a> | '
            '<a href="/audit/missing-folders">Users without a Drive folder</a> | '
            '<a href="/audit/missing-folders?matched=1">Users with a Drive folder</a> | '
            '<a href="/audit/orphan-folders">Folders without an active user</a> | '
            '<a href="/logout">Logout</a></p>'
        )
    return '<h1>AOT Directory</h1><p><a href="/login">Login with Google</a></p>'


@app.get("/login")
def login(request: Request):
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    request.session["oauth_state"] = state
    request.session["code_verifier"] = flow.code_verifier
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
def auth_callback(request: Request):
    state = request.session.get("oauth_state")
    flow = build_flow(state=state)
    flow.code_verifier = request.session.get("code_verifier")
    flow.fetch_token(authorization_response=str(request.url))
    request.session["credentials"] = creds_to_session(flow.credentials)
    return RedirectResponse("/users")


@app.get("/users", response_class=HTMLResponse)
def list_users(request: Request):
    session_creds = request.session.get("credentials")
    if not session_creds:
        return RedirectResponse("/login")

    creds = creds_from_session(session_creds)

    ok, users, source, err = get_directory_users(creds)
    if ok:
        return render_table(users, source=source)

    people_err, admin_err = err
    return f"""
    <h1>Access denied</h1>
    <p>Signed-in account could not list the directory via either API.</p>
    <p>People API error: {describe_error(people_err)}</p>
    <p>Admin SDK error: {describe_error(admin_err)}</p>
    <p><a href="/logout">Logout</a></p>
    """


@app.get("/drive/folders", response_class=HTMLResponse)
def list_drive_folders(request: Request):
    session_creds = request.session.get("credentials")
    if not session_creds:
        return RedirectResponse("/login")

    creds = creds_from_session(session_creds)
    ok, folders, err = fetch_drive_folders(creds, DRIVE_FOLDER_ID)
    if ok:
        return render_folder_table(folders)

    return f"""
    <h1>Access denied</h1>
    <p>Signed-in account could not list this Drive folder.</p>
    <p>Error: {describe_error(err)}</p>
    <p><a href="/logout">Logout</a></p>
    """


@app.get("/audit/missing-folders", response_class=HTMLResponse)
def missing_folders(request: Request):
    session_creds = request.session.get("credentials")
    if not session_creds:
        return RedirectResponse("/login")

    creds = creds_from_session(session_creds)

    users_ok, users, source, users_err = get_directory_users(creds)
    if not users_ok:
        people_err, admin_err = users_err
        return f"""
        <h1>Access denied</h1>
        <p>Could not fetch the directory to run this comparison.</p>
        <p>People API error: {describe_error(people_err)}</p>
        <p>Admin SDK error: {describe_error(admin_err)}</p>
        <p><a href="/logout">Logout</a></p>
        """

    folders_ok, folders, folders_err = fetch_drive_folders(creds, DRIVE_FOLDER_ID)
    if not folders_ok:
        return f"""
        <h1>Access denied</h1>
        <p>Could not fetch the Drive folder listing to run this comparison.</p>
        <p>Error: {describe_error(folders_err)}</p>
        <p><a href="/logout">Logout</a></p>
        """

    folder_names = [f["name"] for f in folders]
    results = []
    for u in users:
        if u["name"] == "No Name":
            continue
        best_name, score = best_match(u["name"], folder_names)
        results.append({"user": u["name"], "best_match": best_name, "score": score})

    show_matched = request.query_params.get("matched") is not None
    return render_user_folder_match_table(results, len(results), len(folders), show_matched)


@app.get("/audit/orphan-folders", response_class=HTMLResponse)
def orphan_folders(request: Request):
    session_creds = request.session.get("credentials")
    if not session_creds:
        return RedirectResponse("/login")

    creds = creds_from_session(session_creds)

    users_ok, users, source, users_err = get_directory_users(creds)
    if not users_ok:
        people_err, admin_err = users_err
        return f"""
        <h1>Access denied</h1>
        <p>Could not fetch the directory to run this comparison.</p>
        <p>People API error: {describe_error(people_err)}</p>
        <p>Admin SDK error: {describe_error(admin_err)}</p>
        <p><a href="/logout">Logout</a></p>
        """

    folders_ok, folders, folders_err = fetch_drive_folders(creds, DRIVE_FOLDER_ID)
    if not folders_ok:
        return f"""
        <h1>Access denied</h1>
        <p>Could not fetch the Drive folder listing to run this comparison.</p>
        <p>Error: {describe_error(folders_err)}</p>
        <p><a href="/logout">Logout</a></p>
        """

    user_names = [u["name"] for u in users if u["name"] != "No Name"]
    results = []
    for f in folders:
        best_name, score = best_match(f["name"], user_names)
        results.append({"folder": f["name"], "best_match": best_name, "score": score})

    orphans = [r for r in results if r["score"] < NAME_MATCH_THRESHOLD]
    show_all = request.query_params.get("all") is not None
    return render_orphan_folders_table(
        orphans, len(results), len(user_names), all_results=results if show_all else None
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
