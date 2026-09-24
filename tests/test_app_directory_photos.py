"""Photo column on the /users directory listing in app.py."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SESSION_SECRET", "test-secret")

import app  # noqa: E402

PHOTO_URL = "https://lh3.googleusercontent.com/a/abc=s100"


def _person(photos):
    return {
        "names": [{"displayName": "Asha Rao"}],
        "emailAddresses": [{"value": "asha@x.com"}],
        "photos": photos,
    }


def _photo(url, primary=True, default=False):
    return {"url": url, "default": default, "metadata": {"primary": primary}}


def _mock_service(method_chain_result: dict, *chain):
    service = MagicMock()
    node = service
    for name in chain:
        node = getattr(node, name).return_value
    node.execute.return_value = method_chain_result
    return service


class TestPrimaryPhotoUrl:
    def test_returns_primary_uploaded_photo(self):
        assert app.primary_photo_url(_person([_photo(PHOTO_URL)])) == PHOTO_URL

    def test_prefers_primary_over_first(self):
        photos = [_photo("https://other", primary=False), _photo(PHOTO_URL)]
        assert app.primary_photo_url(_person(photos)) == PHOTO_URL

    def test_default_generated_avatar_is_ignored(self):
        assert app.primary_photo_url(_person([_photo(PHOTO_URL, default=True)])) is None

    def test_no_photos_key(self):
        assert app.primary_photo_url({"names": []}) is None

    def test_empty_photos_list(self):
        assert app.primary_photo_url(_person([])) is None

    def test_no_primary_photo(self):
        assert app.primary_photo_url(_person([_photo(PHOTO_URL, primary=False)])) is None


class TestFetchersIncludePhoto:
    def test_people_api_requests_photos_and_returns_url(self):
        service = _mock_service(
            {"people": [_person([_photo(PHOTO_URL)])]}, "people", "listDirectoryPeople"
        )
        with patch.object(app, "build", return_value=service):
            ok, users, err = app.fetch_people_api(MagicMock())
        assert ok and err is None
        assert users[0]["photo"] == PHOTO_URL
        read_mask = service.people.return_value.listDirectoryPeople.call_args.kwargs["readMask"]
        assert "photos" in read_mask.split(",")

    def test_admin_sdk_uses_thumbnail_photo_url(self):
        user = {
            "name": {"fullName": "Asha Rao"},
            "primaryEmail": "asha@x.com",
            "thumbnailPhotoUrl": PHOTO_URL,
        }
        service = _mock_service({"users": [user]}, "users", "list")
        with patch.object(app, "build", return_value=service):
            ok, users, _ = app.fetch_admin_sdk(MagicMock())
        assert ok and users[0]["photo"] == PHOTO_URL

    def test_admin_sdk_without_thumbnail(self):
        user = {"name": {"fullName": "Asha Rao"}, "primaryEmail": "asha@x.com"}
        service = _mock_service({"users": [user]}, "users", "list")
        with patch.object(app, "build", return_value=service):
            _, users, _ = app.fetch_admin_sdk(MagicMock())
        assert users[0]["photo"] is None


class TestRenderTablePhotoColumn:
    def _user(self, photo):
        return {"name": "Asha Rao", "emails": ["asha@x.com"], "addresses": [], "photo": photo}

    def test_header_has_photo_column(self):
        assert "<th>Photo</th>" in app.render_table([], source="People API")

    def test_photo_rendered_as_small_icon(self):
        html = app.render_table([self._user(PHOTO_URL)], source="People API")
        assert f'<img src="{PHOTO_URL}"' in html
        assert 'width="32" height="32"' in html
        assert 'alt="Asha Rao"' in html

    def test_missing_photo_shows_dash(self):
        html = app.render_table([self._user(None)], source="People API")
        assert "<img" not in html
        assert "<td>—</td>" in html

    def test_user_without_photo_key(self):
        user = {"name": "Asha Rao", "emails": ["asha@x.com"], "addresses": []}
        assert "<img" not in app.render_table([user], source="Admin SDK")

    def test_photo_url_is_attribute_escaped(self):
        html = app.render_table([self._user('https://x/"onerror="alert(1)')], source="People API")
        assert '"onerror="' not in html
        assert "&quot;onerror=&quot;" in html
