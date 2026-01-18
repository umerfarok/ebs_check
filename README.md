# EBS Unattached Volume Scanner & Cleaner (Safe by Default)

This script lists EBS volumes that are **not attached to any instance** (i.e., volumes in `available` state) and prints their **VolumeId and ARN**.
Optionally, it can delete those volumes — with **DryRun enabled by default** to prevent accidental deletions.

## What it does

✅ Uses the **default AWS credential chain** (no credentials hardcoded).
✅ Scans **one region at a time**.
✅ Finds EBS volumes that are **unattached** (`State = available`).
✅ Prints each volume:
- VolumeId (e.g., `vol-0123456789abcdef0`)
- ARN (e.g., `arn:aws:ec2:us-east-1:123456789012:volume/vol-...`)
- Size, Type, AZ, Name tag (if present)

✅ Two modes of operation:
- **With `--dry-run`:** Lists volumes only (NO deletion)
- **Without `--dry-run`:** Lists and DELETES all unattached volumes
- Re-checks each volume is still unattached immediately before delete

## Requirements

- Python 3.8+
- boto3

Install boto3:

```bash
pip install boto3

## AWS Credentials & Region

The script uses the standard AWS credential lookup order, including:

- Environment variables (AWS_ACCESS_KEY_ID, etc.)
- ~/.aws/credentials and ~/.aws/config (default profile)
- Instance profile / IAM role (if running on EC2)
- Other supported providers

You must have an AWS region configured, either:

- via aws configure, or
- by passing --region

Check your current config:

```bash
aws configure list
```

## IAM Permissions

To list volumes and compute ARNs:

- ec2:DescribeVolumes
- sts:GetCallerIdentity

To delete volumes:

- ec2:DeleteVolume

## Usage

### 1) List unattached volumes with --dry-run (safe, list-only)

Specify region and use --dry-run to list without deleting:

```bash
python ebs_check.py --region us-east-1 --dry-run
```

### 2) Output as JSON

```bash
python ebs_check.py --region us-east-1 --dry-run --output json
```

### 3) Delete unattached volumes (without --dry-run)

**WARNING:** This will ACTUALLY DELETE volumes. Be careful!

```bash
python ebs_check.py --region us-east-1
```

## Safety Guarantees

The script only targets volumes that are unattached, primarily defined as:

- State == "available"

Before deletion, it re-checks each volume's state to reduce race conditions
(e.g., if someone attaches the volume after your listing but before deletion).

**Important:** --dry-run flag prevents deletion. Without it, volumes WILL be deleted.

## Notes / Known Edge Cases

- **Multi-region**: The script operates on one region at a time. Run it per region.
- **Recently detached volumes**: A volume that was detached recently will appear as available and may be deleted. If you want protection, add an "age threshold" filter.
- **EBS Multi-Attach (io1/io2)**: If a volume is attached, it will not be available, so it will not be deleted.
- **AccessDenied**: If you lack ec2:DeleteVolume, deletion will fail; listing will still work.
- **ARN format**: EBS volume ARNs follow:
  `arn:<partition>:ec2:<region>:<account-id>:volume/<volume-id>`
  This script computes that from STS identity + region.

## Recommended Workflow (Best Practice)

### 1. Run listing with --dry-run:

```bash
python ebs_check.py --region <region> --dry-run
```

### 2. Review the output carefully

Make sure the volumes listed are safe to delete.

### 3. If output looks correct, run deletion (without --dry-run):

```bash
python ebs_check.py --region <region>
```

## Disclaimer

This tool deletes AWS resources and may incur data loss if used incorrectly.
Always start with --dry-run mode first, and carefully review the output before running
without --dry-run. Consider adding additional filters (tags / age thresholds) for production use.

---

## Is the script "correct" and bug-free?

I can't honestly guarantee *zero* bugs without running it in your AWS account, but I can tell you what I checked and what's solid:

### What is correct / reliable
- **Default credentials**: `boto3.Session()` uses the standard AWS credential chain. That matches your "default profile creds" requirement.
- **Detecting unattached volumes**: Filtering `status=available` is the standard way to find unattached EBS volumes.
- **ARN generation**: The ARN format used is the correct EC2 volume ARN pattern (`...:volume/vol-...`).
- **Deletion safety**:
  - --dry-run flag prevents deletion (safe mode)
  - Re-check before delete helps prevent deleting something that got attached after listing
  - Clear warnings before deletion occurs

### Small risk / improvement area (not a bug, but safety)
- **"Recently detached" volumes**: Those are `available`, so they will be listed and could be deleted. If you want to avoid deleting something detached minutes ago, add a rule like "only delete if older than X days". (EBS `CreateTime` can be used for this.)
- **Volumes you want to keep** (e.g., snapshots restore staging volumes): the script doesn't currently filter by tag or naming rules unless you add it.

### One practical enhancement I strongly recommend
Add at least one of these:
- `--min-age-days 7` (only delete volumes created > 7 days ago)
- `--exclude-tag Key=Value` (never delete volumes with "Keep=true")
- `--require-tag Cleanup=true` (only delete volumes explicitly marked)

If you want, I can paste an updated version of the script with these safety features.