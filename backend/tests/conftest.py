import pytest


@pytest.fixture(autouse=True)
def isolated_review_policy(monkeypatch):
    monkeypatch.delenv('RIXIN_REVIEW_POLICY', raising=False)


@pytest.fixture(autouse=True)
def isolated_auth_mode(monkeypatch):
    # Business regressions run offline; authentication tests explicitly re-enable it.
    monkeypatch.setenv('RIXIN_AUTH_ENABLED', '0')
