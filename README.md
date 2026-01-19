# EBS Unattached Volume Scanner & Cleaner (Safe by Default)

This script shows comprehensive details for ALL EBS volumes (attached and unattached) and can delete unattached volumes.

## What it does

✅ Uses the **default AWS credential chain** (no credentials hardcoded).
✅ Scans **one region at a time**.
✅ Shows **ALL EBS volumes** (attached and unattached) with comprehensive details.
✅ Displays complete volume information including:
- Volume ID and ARN
- Name, Size, Type, Availability Zone
- State, Creation Time, IOPS, Throughput
- Encryption status, Multi-Attach capability
- All tags (not just Name)
- For attached volumes: Instance ID, Device name, Attachment state
- For unattached volumes: Ready for cleanup status

✅ Two modes of operation:
- **With `--dry-run`:** Lists all volumes (NO deletion)
- **Without `--dry-run`:** Lists all volumes AND deletes unattached ones
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

### 1) List all volumes with --dry-run (safe, list-only)

Shows all EBS volumes (attached and unattached) without deleting anything:

```bash
python ebs_check.py --region us-east-1 --dry-run
```

Example output:
```
Attached EBS volumes in us-east-1 (account 123456789012):
- Volume Details:
  Volume ID: vol-12345678
  ARN: arn:aws:ec2:us-east-1:123456789012:volume/vol-12345678
  Name: web-server-data
  Size: 20 GiB
  Type: gp3
  Availability Zone: us-east-1a
  State: in-use
  Created: 2024-01-15 10:30:45.123000+00:00
  IOPS: 3000
  Throughput: 125 MiB/s
  Encrypted: False
  Multi-Attach: False
  Attachments:
    - Instance: i-1234567890abcdef0, Device: /dev/sda1, State: attached
  Tags:
    - Name: web-server-data
    - Environment: production
    - Team: web-team

================================================================================

Unattached EBS volumes in us-east-1 (account 123456789012):
- Volume Details:
  Volume ID: vol-abcdef12
  ARN: arn:aws:ec2:us-east-1:123456789012:volume/vol-abcdef12
  Name: old-test-volume
  Size: 8 GiB
  Type: gp3
  Availability Zone: us-east-1a
  State: available
  Created: 2024-01-10 14:20:30.456000+00:00
  IOPS: 3000
  Throughput: 125 MiB/s
  Encrypted: False
  Multi-Attach: False
  Tags:
    - Name: old-test-volume
    - Purpose: testing

Summary: Found 1 unattached volume(s) ready for cleanup

--dry-run mode: 1 volume(s) listed above (NOT deleted)
```

### 3) Output as JSON

```bash
python ebs_check.py --region us-east-1 --dry-run --output json
```

### 4) Delete unattached volumes (without --dry-run)

**WARNING:** This will ACTUALLY DELETE volumes. Be careful!

```bash
python ebs_check.py --region us-east-1
```

With verbose mode:
```bash
python ebs_check.py --region us-east-1 --verbose
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