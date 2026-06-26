import base64
import json
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.http import JsonResponse
from hb_backend.decorators import bearer_auth_required, basic_auth_required
from hb_backend.models import ClientKey, current_epoch_int


class TestBearerAuthRequired(TestCase):
    """Tests for the bearer_auth_required decorator."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client_key = ClientKey.objects.create(
            owner=self.user,
            name="test-key",
        )

        # Create a mock view
        @bearer_auth_required
        def mock_view(request):
            return JsonResponse({"status": "ok", "key_id": request.client_key.pk})

        self.mock_view = mock_view

    def test_bearer_auth_valid_token(self):
        """Valid bearer token should be accepted."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {self.client_key.bearer_token}",
        )
        response = self.mock_view(request)
        data = json.loads(response.content)
        assert data["status"] == "ok"
        assert data["key_id"] == self.client_key.pk

    def test_bearer_auth_missing_token(self):
        """Missing bearer token should return 401."""
        request = self.factory.get("/")
        response = self.mock_view(request)
        assert response.status_code == 401
        assert "Unauthorized" in response.content.decode()

    def test_bearer_auth_invalid_token(self):
        """Invalid bearer token should return 401."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION="Bearer invalid-token-12345",
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_bearer_auth_revoked_key(self):
        """Revoked key should not be accepted."""
        self.client_key.is_revoked = True
        self.client_key.save()
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {self.client_key.bearer_token}",
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_bearer_auth_fallback_to_previous_token(self):
        """Should accept previous token if within grace period."""
        old_token = self.client_key.bearer_token
        self.client_key.rotate_keys(overlap_seconds=3600)

        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {old_token}",
        )
        response = self.mock_view(request)
        # Should work with the overlap grace period
        data = json.loads(response.content)
        assert data["status"] == "ok"

    def test_bearer_auth_reject_expired_overlap(self):
        """Should reject previous token after grace period expires."""
        old_token = self.client_key.bearer_token
        self.client_key.rotate_keys(overlap_seconds=-100)  # Already expired

        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {old_token}",
        )
        response = self.mock_view(request)
        assert response.status_code == 401


class TestBasicAuthRequired(TestCase):
    """Tests for the basic_auth_required decorator."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

        # Create a mock view
        @basic_auth_required
        def mock_view(request):
            return JsonResponse({"status": "ok", "username": request.user.username})

        self.mock_view = mock_view

    def _make_basic_auth_header(self, username, password):
        """Helper to create a basic auth header."""
        credentials = f"{username}:{password}".encode()
        encoded = base64.b64encode(credentials).decode()
        return f"Basic {encoded}"

    def test_basic_auth_valid_credentials(self):
        """Valid username/password should authenticate."""
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.auth.middleware import AuthenticationMiddleware
        
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=self._make_basic_auth_header("testuser", "testpass123"),
        )
        # Add session and auth middleware
        SessionMiddleware(lambda x: None).process_request(request)
        AuthenticationMiddleware(lambda x: None).process_request(request)
        request.session.save()
        
        response = self.mock_view(request)
        # When credentials are valid, decorator calls the view (not 401)
        assert response.status_code != 401

    def test_basic_auth_missing_header(self):
        """Missing auth header should return 401."""
        request = self.factory.get("/")
        response = self.mock_view(request)
        assert response.status_code == 401
        assert response["WWW-Authenticate"] == 'Basic realm="Heartbeat API"'

    def test_basic_auth_invalid_credentials(self):
        """Invalid password should return 401."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=self._make_basic_auth_header("testuser", "wrongpassword"),
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_basic_auth_invalid_username(self):
        """Non-existent user should return 401."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=self._make_basic_auth_header("nonexistent", "password"),
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_basic_auth_malformed_header(self):
        """Malformed auth header should return 401."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION="Basic notvalidbase64!!!",
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_basic_auth_wrong_scheme(self):
        """Wrong auth scheme should return 401."""
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=self._make_basic_auth_header("testuser", "testpass123").replace("Basic", "Bearer"),
        )
        response = self.mock_view(request)
        assert response.status_code == 401

    def test_basic_auth_inactive_user(self):
        """Inactive user should return 401."""
        self.user.is_active = False
        self.user.save()
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=self._make_basic_auth_header("testuser", "testpass123"),
        )
        response = self.mock_view(request)
        assert response.status_code == 401
