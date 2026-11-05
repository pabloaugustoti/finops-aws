"""Criação de sessões AWS: perfil do CLI (conta hub) e AssumeRole (contas monitoradas)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from finops.accounts import Account

if TYPE_CHECKING:
    import boto3

BILLING_REGION = "us-east-1"  # Cost Explorer e Budgets respondem nesta região
SESSION_NAME = "finops-coletor"
# Perfil especial: usa as credenciais do ambiente (variáveis AWS_*), como as que o
# GitHub Actions recebe via OIDC. Nenhum perfil do AWS CLI é necessário.
ENVIRONMENT_PROFILE = "ambiente"


def profile_session(profile: str) -> boto3.Session:
    """Sessão do perfil do AWS CLI (ou das credenciais do ambiente, com o perfil "ambiente").

    Se o perfil não tiver região padrão, usamos us-east-1: a renovação automática das
    credenciais do `aws login` precisa de uma região, e sem ela tudo falha com
    "You must specify a region" depois que o primeiro token expira.
    """
    import boto3

    if profile == ENVIRONMENT_PROFILE:
        session = boto3.Session()
        return session if session.region_name else boto3.Session(region_name=BILLING_REGION)

    session = boto3.Session(profile_name=profile)
    if session.region_name is None:
        session = boto3.Session(profile_name=profile, region_name=BILLING_REGION)
    return session


def assume_role_session(sts_client: Any, account: Account, duration_seconds: int = 3600) -> boto3.Session:
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
