#!/usr/bin/env python3
"""
List and delete unattached EBS volumes using default AWS credentials.

Usage:
  # List unattached volumes (with --dry-run, no deletion)
  python ebs_check.py --region us-east-1 --dry-run

  # List with verbose logging (shows all volumes: attached + unattached)
  python ebs_check.py --region us-east-1 --dry-run --verbose

  # Delete unattached volumes (without --dry-run)
  python ebs_check.py --region us-east-1

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


def describe_all_volumes(ec2) -> List[Dict]:
    """Get all EBS volumes in the region."""
    paginator = ec2.get_paginator("describe_volumes")
    pages = paginator.paginate()

    vols = []
    for page in pages:
        vols.extend(page.get("Volumes", []))
    return vols


def describe_unattached_volumes(ec2) -> List[Dict]:
    """Unattached EBS volumes are those with State == 'available'."""
    paginator = ec2.get_paginator("describe_volumes")
    pages = paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}])

    vols = []
    for page in pages:
        vols.extend(page.get("Volumes", []))
    return vols




def is_unattached(volume: Dict) -> bool:
    # Most reliable: State == 'available'
    if volume.get("State") == "available":
        return True
    # Extra guard: if AWS ever returns attachments empty but state differs
    atts = volume.get("Attachments", [])
    return len(atts) == 0


def delete_volume(ec2, volume_id: str) -> Tuple[bool, str]:
    """Attempt deletion. Returns (ok, message)."""
    try:
        ec2.delete_volume(VolumeId=volume_id)
        return True, "Deleted"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        return False, f"{code}: {msg}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List/delete unattached EBS volumes. Use --dry-run to only list without deleting. Use --verbose for detailed logging."
    )
    ap.add_argument("--region", help="AWS region (defaults to your configured region).")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, only list unattached volumes without deleting them.",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="If set, show detailed logging of all volumes (attached and unattached).",
    )
    ap.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format for listing (default: text).",
    )

    args = ap.parse_args()

    # Default credential chain
    session = boto3.Session(region_name=args.region)

    region = session.region_name
    if not region:
        print(
            "ERROR: No region set. Use --region or configure a default region (aws configure).",
            file=sys.stderr,
        )
        return 2

    ec2 = session.client("ec2", region_name=region)
    partition, account_id = get_identity(session)

    # Get volume information
    if args.verbose:
        print(f"Scanning all EBS volumes in {region} (account {account_id})...")
        all_volumes = describe_all_volumes(ec2)

        # Analyze volume states
        total_volumes = len(all_volumes)
        unattached_volumes = [v for v in all_volumes if is_unattached(v)]
        attached_volumes = [v for v in all_volumes if not is_unattached(v)]

        print(f"Total EBS volumes found: {total_volumes}")
        print(f"Unattached volumes: {len(unattached_volumes)}")
        print(f"Attached volumes: {len(attached_volumes)}")

        if attached_volumes:
            print(f"\nAttached volumes:")
            for v in attached_volumes:
                vid = v["VolumeId"]
                size = v.get("Size", 0)
                vtype = v.get("VolumeType", "unknown")
                state = v.get("State", "unknown")
                az = v.get("AvailabilityZone", "unknown")
                tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])} if v.get("Tags") else {}
                name = tags.get("Name", "")

                attachment_info = ""
                if v.get("Attachments"):
                    att = v["Attachments"][0]
                    instance_id = att.get("InstanceId", "unknown")
                    attachment_info = f" (attached to {instance_id})"

                print(f"  - {vid}: {size}GiB {vtype} in {az}, State={state}{attachment_info}")
                if name:
                    print(f"    Name: {name}")

        print(f"\n" + "="*50)
        vols = unattached_volumes
    else:
        # Get only unattached volumes
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
            if args.verbose:
                print(f"No unattached EBS volumes found in {region}.")
            else:
                print(f"No unattached EBS volumes found in {region}.")
        else:
            print(f"Unattached EBS volumes in {region} (account {account_id}):")
            for r in rows:
                extra = f" Size={r['SizeGiB']}GiB Type={r['Type']} AZ={r['AZ']}"
                if r["NameTag"]:
                    extra += f" Name={r['NameTag']!r}"
                print(f"- {r['VolumeId']}  {r['Arn']}{extra}")

        if args.verbose:
            print(f"\nSummary: Found {len(rows)} unattached volume(s) ready for cleanup")

    # Deletion logic
    if args.dry_run:
        # Dry-run mode: only list, no deletion
        if rows:
            print(f"\n--dry-run mode: {len(rows)} volume(s) listed above (NOT deleted)")
        elif args.verbose:
            print(f"\n--dry-run mode: No unattached volumes to delete")
        return 0
    else:
        # No dry-run: proceed with deletion
        if not rows:
            if args.verbose:
                print(f"\nNo unattached volumes to delete")
            return 0

        if args.verbose:
            print(f"\n⚠️  DELETING {len(rows)} unattached volume(s)...")
            print("This action cannot be undone. Double-checking volumes before deletion...")
        else:
            print(f"\n⚠️  DELETING {len(rows)} unattached volume(s)...")
        ok_count = 0
        fail_count = 0

        for r in rows:
            vid = r["VolumeId"]

            # Re-check safety right before delete
            try:
                resp = ec2.describe_volumes(VolumeIds=[vid])
                vinfo = resp.get("Volumes", [])
                if not vinfo or not is_unattached(vinfo[0]):
                    fail_count += 1
                    print(f"✗ SKIP {vid}: volume is no longer unattached")
                    continue
            except ClientError:
                fail_count += 1
                print(f"✗ SKIP {vid}: unable to verify volume status")
                continue

            ok, msg = delete_volume(ec2, vid)
            if ok:
                ok_count += 1
                print(f"✓ {vid}: {msg}")
            else:
                fail_count += 1
                print(f"✗ {vid}: {msg}")

        print(f"\n✅ Summary: deleted={ok_count} failed/skipped={fail_count}")
        if fail_count == 0:
            print("All deletions completed successfully.")
        return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
