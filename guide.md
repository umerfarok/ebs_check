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

✅ Optional delete mode:
- `--delete` enables delete mode
- deletion runs in **DryRun** by default
- `--no-dry-run` performs actual deletion (dangerous; use carefully)
- re-checks each volume is still unattached immediately before delete

## Requirements

- Python 3.8+
- boto3

Install boto3:

```bash
pip install boto3
