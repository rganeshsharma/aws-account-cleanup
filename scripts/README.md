# AWS Resource Cleanup Scripts

A collection of safe, interactive Python scripts for cleaning up unused AWS resources and reducing cloud costs.

## 🚀 Overview

These scripts help you identify and delete unused AWS resources that may be costing you money:

- **EBS Snapshots** (`snapshot_cleanup.py`) - Delete unused EBS snapshots
- **EBS Volumes** (`volume_cleanup.py`) - Delete unattached EBS volumes  
- **S3 Buckets** (`s3_cleanup.py`) - Delete S3 buckets and all their contents

### Key Features

✅ **Safety First** - Multiple confirmation prompts and safety warnings  
✅ **Cost Analysis** - Shows estimated monthly/annual savings  
✅ **Smart Detection** - Identifies potentially important resources  
✅ **Selective Deletion** - Choose exactly what to delete  
✅ **Detailed Reporting** - Shows progress and results  
✅ **Dry-Run Mode** - Test without making changes  
✅ **Multi-Region Support** - Works across all accessible AWS regions  

## 📋 Prerequisites

### Required Software
- **Python 3.7+** 
- **AWS CLI** configured with appropriate credentials
- **boto3** Python library

### AWS Permissions

Your AWS credentials need the following permissions:

#### For EBS Snapshots:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeSnapshots",
                "ec2:DeleteSnapshot",
                "ec2:DescribeRegions"
            ],
            "Resource": "*"
        }
    ]
}
```

#### For EBS Volumes:
```json
{
    "Version": "2012-10-17", 
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeVolumes",
                "ec2:DeleteVolume",
                "ec2:DescribeRegions"
            ],
            "Resource": "*"
        }
    ]
}
```

#### For S3 Buckets:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:ListBucket",
                "s3:ListBucketVersions",
                "s3:DeleteObject",
                "s3:DeleteObjectVersion", 
                "s3:DeleteBucket",
                "s3:GetBucketLocation",
                "s3:GetBucketVersioning",
                "cloudwatch:GetMetricStatistics"
            ],
            "Resource": "*"
        }
    ]
}
```

## 🛠️ Installation

### 1. Install Dependencies
```bash
# Install boto3
pip install boto3

# Or install from requirements.txt (if provided)
pip install -r requirements.txt
```

### 2. Configure AWS CLI
```bash
# Configure default profile
aws configure

# Or configure a specific profile
aws configure --profile dev
```

### 3. Download Scripts
Download the Python scripts to your local machine:
- `snapshot_cleanup.py`
- `volume_cleanup.py` 
- `s3_cleanup.py`

### 4. Make Scripts Executable
```bash
chmod +x *.py
```

## 🎯 Usage

### EBS Snapshots Cleanup

Delete unused EBS snapshots to save on storage costs (~$0.05/GB-month).

```bash
# Basic usage with default profile
python3 snapshot_cleanup.py

# Use specific AWS profile
python3 snapshot_cleanup.py --profile dev

# Get help
python3 snapshot_cleanup.py --help
```

**Sample Output:**
```
SNAPSHOT SUMMARY
================================================================================
AWS Account ID: 123456789012
Total snapshots found: 15
Total storage size: 450 GB
Regions scanned: us-east-1, ap-south-1
Estimated monthly savings: $22.50

Do you want to DELETE ALL 15 snapshots? (y/n):
```

### EBS Volumes Cleanup

Delete unattached EBS volumes (won't touch volumes attached to running instances).

```bash
# Basic usage
python3 volume_cleanup.py

# With specific profile
python3 volume_cleanup.py --profile production
```

**Sample Output:**
```
VOLUME SUMMARY
================================================================================
AWS Account ID: 123456789012
Total volumes found: 25
Attached volumes: 18
Available (unattached) volumes: 7
Potential monthly savings from deleting available volumes: $45.60

⚠️  WARNING: You are about to delete 7 available volumes
Do you want to proceed with volume deletion? (y/n):
```

### S3 Buckets Cleanup

Delete S3 buckets and all their contents with smart safety warnings.

```bash
# Basic usage
python3 s3_cleanup.py

# Dry-run mode (recommended first)
python3 s3_cleanup.py --dry-run

# With specific profile
python3 s3_cleanup.py --profile dev

# Dry-run with specific profile
python3 s3_cleanup.py --profile dev --dry-run
```

**Sample Output:**
```
S3 BUCKET SUMMARY
================================================================================
Total buckets found: 8
Total storage size: 2.3 GB
Estimated monthly cost: $52.80
Buckets with safety warnings: 3

SELECT BUCKETS TO DELETE
==================================================
 1. my-old-backup-bucket           |    1.2 GB | $27.60/mo | ⚠
 2. temp-storage-test              |   850 MB  | $19.55/mo | ✓
 3. website-assets-old             |   450 MB  | $10.35/mo | ⚠

Your selection: 2
```

## ⚠️ Safety Features

### Built-in Safety Measures

1. **Multiple Confirmations** - Scripts ask for confirmation multiple times
2. **Safety Warnings** - Identifies potentially important resources
3. **Attachment Checking** - Won't delete volumes attached to instances  
4. **Dry-Run Mode** - Test S3 deletions without making changes
5. **Detailed Preview** - Shows exactly what will be deleted and cost impact

### Resource Safety Detection

The scripts automatically warn about:

**EBS Volumes:**
- Volumes attached to running instances
- Volumes with important-looking names/tags

**S3 Buckets:**
- Buckets with names containing: backup, prod, website, cdn, logs
- Buckets with versioning enabled
- Buckets with lifecycle policies
- Buckets with public access

## 💰 Cost Savings Examples

### Typical Savings Scenarios

| Resource Type | Unused Amount | Monthly Cost | Annual Savings |
|---------------|---------------|--------------|----------------|
| EBS Snapshots | 100 GB | $5.00 | $60.00 |
| EBS Volumes (gp3) | 200 GB | $16.00 | $192.00 |
| S3 Standard Storage | 50 GB | $1.15 | $13.80 |
| **Total Example** | - | **$22.15** | **$265.80** |

### Real Customer Examples

- **Startup**: Saved $180/month by cleaning up old snapshots and unused volumes
- **Development Team**: Saved $350/month by removing test S3 buckets  
- **Enterprise**: Saved $1,200/month across multiple AWS accounts

## 🔧 Troubleshooting

### Common Issues

#### "No accessible regions found"
```bash
# Test your AWS connectivity
aws sts get-caller-identity
aws ec2 describe-regions --region us-east-1
```

#### "AWS credentials not found"
```bash
# Configure AWS CLI
aws configure

# Or check existing profiles
aws configure list-profiles
```

#### "Access Denied" errors
- Check your IAM permissions match the prerequisites above
- Ensure your user/role has sufficient permissions
- Try with a different AWS profile

#### S3 bucket deletion fails
```bash
# Try dry-run first to identify issues
python3 s3_cleanup.py --dry-run

# Check bucket permissions manually
aws s3api get-bucket-location --bucket your-bucket-name
```

#### Script appears stuck
- S3 analysis can take time for buckets with many objects
- Large snapshots/volumes lists take time to process
- Check your network connectivity to AWS

### Debug Mode

Add debug output to any script:
```bash
# Add this at the top of the script after imports
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🚨 Important Warnings

### ⚠️ CRITICAL SAFETY REMINDERS

1. **IRREVERSIBLE ACTIONS** - Deleted resources cannot be recovered
2. **TEST FIRST** - Always run scripts on test accounts before production
3. **USE DRY-RUN** - Use `--dry-run` for S3 cleanup to preview changes  
4. **CHECK ATTACHMENTS** - Volume script won't delete attached volumes, but double-check
5. **BACKUP IMPORTANT DATA** - Ensure important data is backed up elsewhere
6. **UNDERSTAND COSTS** - Understand what you're deleting and why

### 🔐 Security Best Practices

1. **Principle of Least Privilege** - Only grant necessary permissions
2. **Use Temporary Credentials** - Consider using AWS STS for temporary access
3. **Audit Trail** - Enable CloudTrail to log all deletion activities
4. **Multi-Factor Authentication** - Use MFA for accounts with deletion permissions

## 📈 Best Practices

### Before Running Scripts

1. **Inventory Check** - Understand what resources you actually need
2. **Cost Analysis** - Review AWS Cost Explorer for unused resources
3. **Tag Strategy** - Tag resources properly for easier identification
4. **Backup Strategy** - Ensure critical data is backed up

### Running the Scripts

1. **Start Small** - Test on a few resources first
2. **Use Dry-Run** - Always test S3 cleanup with `--dry-run` first
3. **Off-Peak Hours** - Run during low-usage times
4. **One Region at a Time** - For large cleanups, process regions separately

### After Running Scripts

1. **Monitor Costs** - Check your AWS bill to confirm savings
2. **Update Processes** - Implement processes to prevent resource sprawl
3. **Regular Cleanup** - Schedule regular cleanup sessions
4. **Document Changes** - Keep records of what was deleted

## 🤝 Contributing

### Reporting Issues

If you encounter problems:

1. **Check Prerequisites** - Ensure all requirements are met
2. **Try Dry-Run** - Use dry-run mode to identify issues
3. **Collect Information** - Include error messages and AWS account region
4. **Check Permissions** - Verify IAM permissions are correct

### Feature Requests

Potential enhancements:
- Additional resource types (Lambda, RDS, etc.)
- Cost optimization recommendations
- Integration with AWS Cost Explorer
- Automated scheduling options

## 📄 License

These scripts are provided as-is for educational and operational use. Please review and test thoroughly before using in production environments.

## ⚡ Quick Start Checklist

- [ ] Install Python 3.7+
- [ ] Install boto3: `pip install boto3`
- [ ] Configure AWS CLI: `aws configure`  
- [ ] Test credentials: `aws sts get-caller-identity`
- [ ] Download scripts
- [ ] **IMPORTANT**: Start with dry-run mode for S3
- [ ] Run on test account first
- [ ] Review all confirmations carefully
- [ ] Monitor AWS costs after cleanup

## 📞 Support

Remember:
- **Test thoroughly** before using on production accounts
- **Understand the costs** and implications before deletion
- **Keep backups** of important data
- **Use dry-run mode** when available

---

**⚠️ FINAL REMINDER: These scripts perform irreversible deletions. Always test on non-production accounts first and ensure you have proper backups of important data.**