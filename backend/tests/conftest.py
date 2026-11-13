"""Pin the historical suite's five-rule contract; candidate tests opt in explicitly.

Default-policy coverage removes this fixture's override and exercises the shipped
seven-rule default. This keeps old-version regression independent of deployment.
"""
import pytest


@pytest.fixture(autouse=True)
def historical_policy_baseline(monkeypatch):
    monkeypatch.setenv('RIXIN_REVIEW_POLICY','redlines-v7')
