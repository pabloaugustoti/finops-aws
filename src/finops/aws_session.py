"""Criação de sessões AWS: perfil do CLI (conta hub) e AssumeRole (contas monitoradas)."""

from __future__ import annotations

from typing import Any

from finops.accounts import Account

BILLING_REGION = "us-east-1"  # Cost Explorer e Budgets respondem nesta região
SESSION_NAME = "finops-coletor"


def profile_session(profile: str):
    import boto3

    return boto3.Session(profile_name=profile)


def assume_role_session(sts_client: Any, account: Account, duration_seconds: int = 3600):
    """Assume a role somente leitura da conta e devolve uma sessão boto3 com credenciais temporárias.

    As credenciais ficam só em memória e expiram sozinhas (no máximo 1 h).
    """
    import boto3

    params: dict[str, Any] = {
        "RoleArn": account.role_arn,
        "RoleSessionName": SESSION_NAME,
        "DurationSeconds": duration_seconds,
    }
    if account.external_id:
        params["ExternalId"] = account.external_id
    credentials = sts_client.assume_role(**params)["Credentials"]
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
