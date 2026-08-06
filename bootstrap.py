"""
bootstrap.py
Handles AWS authentication, AssumeRole, boto3 Session creation, and region discovery.
Shared by all client health-check runners (BHFS, FleetCor, VISA, SMBC, ...).
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# IAM role assumed in every client account (matches DailyChecksFramework/config.py).
ROLE_NAME = "FinOpsAutomationRole"

# AWS account IDs per client, sourced from DailyChecksFramework/config.py.
CLIENTS = {
    "ATB": {"business_region": "NA", "account_id": "578236091839"},
    "BoQ": {"business_region": "APAC", "account_id": "340333144889"},
    "BHFS": {"business_region": "EMEA", "account_id": "476149950471"},
    "Coop": {"business_region": "EMEA", "account_id": "450683977817"},
    "Equifax": {"business_region": "EMEA", "account_id": "386062453979"},
    "FleetCor": {"business_region": "NA", "account_id": "444521715692"},
    "Generali": {"business_region": "EMEA", "account_id": "078988040627"},
    "IAG": {"business_region": "APAC", "account_id": "402366105298"},
    "LFS": {"business_region": "APAC", "account_id": "616476889381"},
    "MGL": {"business_region": "APAC", "account_id": "984546913585"},
    "Mizuho": {"business_region": "EMEA", "account_id": "425998559800"},
    "NBS": {"business_region": "EMEA", "account_id": "720186310367"},
    "Suncorp": {"business_region": "APAC", "account_id": "889716922160"},
    "TabCorp": {"business_region": "APAC", "account_id": "590183781567"},
}


@dataclass
class AWSContext:
    """Holds an authenticated boto3 Session plus the discovered regions."""

    session: boto3.Session
    account_id: str
    regions: list[str]


def get_base_session(profile: Optional[str] = None) -> boto3.Session:
    """Create the initial (master account) boto3 session, optionally using a named profile."""
    if profile:
        return boto3.Session(profile_name=profile)
    return boto3.Session()


def assume_role(session: boto3.Session, account_id: str, role_name: str = ROLE_NAME,
                 session_name: str = "HealthCheckSession") -> boto3.Session:
    """Assume the client's IAM role and return a new boto3 Session using the temporary credentials."""
    sts_client = session.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    try:
        response = sts_client.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
    except ClientError:
        logger.exception("Failed to assume role %s", role_arn)
        raise

    creds = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def discover_regions(session: boto3.Session) -> list[str]:
    """Return only the regions that actually contain EC2 instances for this account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    all_regions = ec2.describe_regions()["Regions"]

    active_regions = []
    for region in all_regions:
        region_name = region["RegionName"]
        client = session.client("ec2", region_name=region_name)
        try:
            response = client.describe_instances()
            if response["Reservations"]:
                active_regions.append(region_name)
        except Exception:
            logger.exception("Failed to check region %s for active instances", region_name)

    return active_regions


def get_account_id(session: boto3.Session) -> str:
    """Return the AWS account ID associated with the session's credentials."""
    return session.client("sts").get_caller_identity()["Account"]


def bootstrap(account_id: str, role_name: str = ROLE_NAME, profile: Optional[str] = None) -> AWSContext:
    """Entry point used by client runners: assumes the client's role and discovers active regions."""
    base_session = get_base_session(profile=profile or os.environ.get("AWS_PROFILE"))
    session = assume_role(base_session, account_id, role_name=role_name)

    regions = discover_regions(session)

    logger.info("Bootstrapped AWS session for account %s across %d active regions", account_id, len(regions))
    return AWSContext(session=session, account_id=account_id, regions=regions)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ctx = bootstrap(account_id=CLIENTS["BHFS"]["account_id"])
    print(f"Account: {ctx.account_id}")
    print(f"Regions: {', '.join(ctx.regions)}")
