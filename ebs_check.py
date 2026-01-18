#!/usr/bin/env python3
"""
List (and optionally delete) unattached EBS volumes using default AWS credentials.

Defaults:
- Lists ONLY unattached volumes (State=available).
- If --delete is used, deletion runs in --dry-run mode by default.

Examples:
  # List unattached volumes in configured default region
  python ebs_orphan_volumes.py

  # List in a specific region
  python ebs_orphan_volumes.py --region us-east-1

  # Delete *all* unattached volumes found in scan (DRY RUN by default)
  python ebs_orphan_volumes.py --region us-east-1 --delete

  # Actually delete all unattached volumes found in scan (requires explicit flag)
  python ebs_orphan_volumes.py --region us-east-1 --delete --no-dry-run

  # Delete only specific volume IDs (still checks they're unattached)
  python ebs_orphan_volumes.py --region us-east-1 --delete --volume-ids vol-0123 vol-0456

Requirements:
  pip install boto3
"""

import argparse
import sys
from typing import Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError


def get_identity(session) -> Tuple[str, str]:
    """Return (partition, account_id) using STS."""
    sts = session.client("sts")
    ident = sts.get_caller_identity()
    account_id = ident["Account"]
    # ident["Arn"] looks like: arn:aws:iam::123456789012:user/...
    arn = ident.get("Arn", "arn:aws:iam::000000000000:root")
    partition = arn.split(":")[1] if arn.startswith("arn:") else "aws"
    return partition, account_id


def volume_arn(partition: str, region: str, account_id: str, volume_id: str) -> str:
    return f"arn:{partition}:ec2:{region}:{account_id}:volume/{volume_id}"


def describe_unattached_volumes(ec2) -> List[Dict]:
    """Unattached EBS volumes are those with State == 'available'."""
    paginator = ec2.get_paginator("describe_volumes")
    pages = paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}])

    vols = []
    for page in pages:
        vols.extend(page.get("Volumes", []))
    return vols


def describe_specific_volumes(ec2, volume_ids: List[str]) -> List[Dict]:
    """Fetch specific volumes by id (handles pagination internally by AWS)."""
    # EC2 API accepts up to 500 ids per request; chunk just in case.
    vols: List[Dict] = []
    chunk_size = 200
    for i in range(0, len(volume_ids), chunk_size):
        chunk = volume_ids[i : i + chunk_size]
        resp = ec2.describe_volumes(VolumeIds=chunk)
        vols.extend(resp.get("Volumes", []))
    return vols


def is_unattached(volume: Dict) -> bool:
    # Most reliable: State == 'available'
    if volume.get("State") == "available":
        return True
    # Extra guard: if AWS ever returns attachments empty but state differs
    atts = volume.get("Attachments", [])
    return len(atts) == 0


def delete_volume(ec2, volume_id: str, dry_run: bool) -> Tuple[bool, str]:
    """Attempt deletion. Returns (ok, message)."""
    try:
        ec2.delete_volume(VolumeId=volume_id, DryRun=dry_run)
        # If DryRun=False and it succeeds, we reach here.
        return True, "Deleted"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))

        # Expected for DryRun=True when permissions + request would succeed
        if dry_run and code == "DryRunOperation":
            return True, "DryRun OK (would delete)"
        return False, f"{code}: {msg}"


def main() -> int:
    ap = argparse.ArgumentParser(description="List/delete unattached EBS volumes (safe by default).")
    ap.add_argument("--region", help="AWS region (defaults to your configured region).")
    ap.add_argument(
        "--delete",
        action="store_true",
        help="If set, delete volumes (still verifies each is unattached). Default is list-only.",
    )
    ap.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="When deleting, use EC2 DryRun (DEFAULT).",
    )
    ap.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="When deleting, actually delete. Use with extreme care.",
    )
    ap.add_argument(
        "--volume-ids",
        nargs="*",
        default=None,
        help="If provided, operate only on these volume IDs (still checks they're unattached).",
    )
    ap.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format for listing (default: text).",
    )

    args = ap.parse_args()

    # Default credential chain will pick up:
    # - env vars, then
    # - ~/.aws/credentials & ~/.aws/config, then
    # - instance/role creds, etc.
    session = boto3.Session(region_name=args.region)

    region = session.region_name
    if not region:
        print("ERROR: No region set. Use --region or configure a default region (aws configure).", file=sys.stderr)
        return 2

    ec2 = session.client("ec2", region_name=region)
    partition, account_id = get_identity(session)

    # Choose scan mode
    if args.volume_ids:
        vols = describe_specific_volumes(ec2, args.volume_ids)
        # Filter to unattached only (safety)
        vols = [v for v in vols if is_unattached(v)]
    else:
        vols = describe_unattached_volumes(ec2)

    # Build result rows
    rows = []
    for v in vols:
        vid = v["VolumeId"]
        arn = volume_arn(partition, region, account_id, vid)
        size = v.get("Size")
        vtype = v.get("VolumeType")
        az = v.get("AvailabilityZone")
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])} if v.get("Tags") else {}
        name = tags.get("Name", "")
        rows.append(
            {
                "VolumeId": vid,
                "Arn": arn,
                "SizeGiB": size,
                "Type": vtype,
                "AZ": az,
                "NameTag": name,
            }
        )

    # Output listing
    if args.output == "json":
        import json

        print(json.dumps(rows, indent=2))
    else:
        if not rows:
            print(f"No unattached EBS volumes found in {region}.")
        else:
            print(f"Unattached EBS volumes in {region} (account {account_id}):")
            for r in rows:
                extra = f" Size={r['SizeGiB']}GiB Type={r['Type']} AZ={r['AZ']}"
                if r["NameTag"]:
                    extra += f" Name={r['NameTag']!r}"
                print(f"- {r['VolumeId']}  {r['Arn']}{extra}")

    # Optional deletion
    if args.delete:
        if not rows:
            return 0

        mode = "DRY RUN" if args.dry_run else "ACTUAL DELETE"
        print(f"\nDelete mode: {mode}")
        ok_count = 0
        fail_count = 0

        for r in rows:
            vid = r["VolumeId"]

            # Re-check safety right before delete
            vinfo = describe_specific_volumes(ec2, [vid])
            if not vinfo or not is_unattached(vinfo[0]):
                fail_count += 1
                print(f"! SKIP {vid}: volume is no longer unattached")
                continue

            ok, msg = delete_volume(ec2, vid, dry_run=args.dry_run)
            if ok:
                ok_count += 1
                print(f"+ {vid}: {msg}")
            else:
                fail_count += 1
                print(f"! {vid}: {msg}")

        print(f"\nSummary: ok={ok_count} failed/skipped={fail_count}")
        if not args.dry_run and fail_count == 0:
            print("All requested deletions completed.")
        return 0 if fail_count == 0 else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
