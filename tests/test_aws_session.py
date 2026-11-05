import pytest

from finops.aws_session import BILLING_REGION, ENVIRONMENT_PROFILE, profile_session


@pytest.fixture
def env_credentials(monkeypatch, tmp_path):
    # Isola do ~/.aws real e simula as credenciais que o GitHub Actions recebe via OIDC
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIATESTEAMBIENTE00")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s" * 40)
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token-oidc")
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)


def test_environment_profile_uses_environment_credentials(env_credentials):
    session = profile_session(ENVIRONMENT_PROFILE)
    credentials = session.get_credentials()
    assert credentials.access_key == "ASIATESTEAMBIENTE00"
    assert credentials.token == "token-oidc"
    assert session.region_name == BILLING_REGION


def test_environment_profile_keeps_region_from_environment(env_credentials, monkeypatch):
    # o botocore lê AWS_DEFAULT_REGION (a action configure-aws-credentials define as duas)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    assert profile_session(ENVIRONMENT_PROFILE).region_name == "us-east-2"
