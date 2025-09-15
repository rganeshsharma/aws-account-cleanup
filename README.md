# AWS Resource Cleanup Scripts - Complete Collection

A comprehensive collection of safe, interactive Python scripts for cleaning up unused AWS resources and drastically reducing cloud costs across all major services.

## 🚀 Overview

These scripts help you identify and delete unused AWS resources that may be costing you hundreds or thousands of dollars per month:

### 📦 Complete Script Collection

| Script | Service | Typical Monthly Cost | Savings Potential |
|--------|---------|---------------------|-------------------|
| `snapshot_cleanup.py` | **EBS Snapshots** | $0.05/GB | $50-200/month |
| `volume_cleanup.py` | **EBS Volumes** | $0.08-0.30/GB | $100-500/month |
| `s3_cleanup.py` | **S3 Buckets** | $0.023/GB + requests | $50-1000/month |
| `lambda_cleanup.py` | **Lambda Functions** | $0.20/1M requests | $20-100/month |
| `loadbalancer_cleanup.py` | **Load Balancers** | $18-22/month each | $100-2000/month |
| `rds_cleanup.py` | **RDS Databases** | $50-500/month each | $200-5000/month |
| `elasticache_cleanup.py` | **ElastiCache** | $20-200/month each | $100-2000/month |
| `kms_cleanup.py` | **KMS Keys** | $1/month each | $10-100/month |
| `secrets_cleanup.py` | **Secrets Manager** | $0.40/month each | $10-200/month |
| `efs_cleanup.py` | **EFS File Systems** | $0.30/GB | $50-500/month |
| `eks_cleanup.py` | **EKS Clusters** | $72/month + nodes | $200-5000/month |

### ✨ Key Features

✅ **Safety First** - Multiple confirmation prompts and safety warnings  
✅ **Cost Analysis** - Shows estimated monthly/annual savings for each resource  
✅ **Smart Detection** - Identifies potentially important resources automatically  
✅ **Selective Deletion** - Choose exactly what to delete with granular control  
✅ **Detailed Reporting** - Shows progress, results, and cost impact  
✅ **Dry-Run Mode** - Test without making changes (available for most scripts)  
✅ **Multi-Region Support** - Works across all accessible AWS regions  
✅ **Network Resilient** - Handles connectivity issues gracefully  

## 📋 Prerequisites

### Required Software
- **Python 3.7+** 
- **AWS CLI** configured with appropriate credentials
- **boto3** Python library: `pip install boto3`

### AWS Permissions

Your AWS credentials need comprehensive permissions. Here are the required policies for each service:

#### Core EC2 & Storage Services
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeSnapshots",
                "ec2:DeleteSnapshot",
                "ec2:DescribeVolumes",
                "ec2:DeleteVolume",
                "ec2:DescribeRegions",
                "ec2:DescribeInstances"
            ],
            "Resource": "*"
        }
    ]
}
```

#### S3 and Storage
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
                "efs:DescribeFileSystems",
                "efs:DeleteFileSystem",
                "efs:DescribeMountTargets",
                "efs:DeleteMountTarget",
                "efs:DescribeAccessPoints",
                "efs:DeleteAccessPoint"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Compute Services
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "lambda:ListFunctions",
                "lambda:DeleteFunction",
                "lambda:GetFunction",
                "lambda:ListEventSourceMappings",
                "eks:ListClusters",
                "eks:DescribeCluster",
                "eks:DeleteCluster",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup",
                "eks:DeleteNodegroup",
                "eks:ListFargateProfiles",
                "eks:DescribeFargateProfile",
                "eks:DeleteFargateProfile",
                "eks:ListAddons",
                "eks:DescribeAddon",
                "eks:DeleteAddon"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Database Services
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "rds:DescribeDBInstances",
                "rds:DeleteDBInstance",
                "rds:DescribeDBClusters",
                "rds:DeleteDBCluster",
                "elasticache:DescribeCacheClusters",
                "elasticache:DeleteCacheCluster",
                "elasticache:DescribeReplicationGroups",
                "elasticache:DeleteReplicationGroup"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Network Services
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DeleteLoadBalancer",
                "elasticloadbalancingv2:DescribeLoadBalancers",
                "elasticloadbalancingv2:DeleteLoadBalancer",
                "elasticloadbalancingv2:DescribeTargetGroups",
                "elasticloadbalancingv2:DescribeTargetHealth"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Security & Management Services
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "kms:ListKeys",
                "kms:DescribeKey",
                "kms:ScheduleKeyDeletion",
                "kms:ListAliases",
                "kms:ListGrants",
                "kms:GetKeyPolicy",
                "secretsmanager:ListSecrets",
                "secretsmanager:DescribeSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:RestoreSecret"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Monitoring (for usage metrics)
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:GetMetricStatistics",
                "cloudtrail:LookupEvents"
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

# Or install all requirements
pip install boto3 argparse
```

### 2. Configure AWS CLI
```bash
# Configure default profile
aws configure

# Or configure a specific profile
aws configure --profile <profile_name>

# eg  
aws configure --profile dev
```

### 3. Download Scripts
Download all Python scripts to your local machine:
- `snapshot_cleanup.py` - EBS Snapshots
- `volume_cleanup.py` - EBS Volumes  
- `s3_cleanup.py` - S3 Buckets
- `lambda_cleanup.py` - Lambda Functions
- `loadbalancer_cleanup.py` - Load Balancers
- `rds_cleanup.py` - RDS Databases
- `elasticache_cleanup.py` - ElastiCache
- `kms_cleanup.py` - KMS Keys
- `secrets_cleanup.py` - Secrets Manager
- `efs_cleanup.py` - EFS File Systems
- `eks_cleanup.py` - EKS Clusters

### 4. Make Scripts Executable
```bash
chmod +x *.py
```

## 🎯 Usage Guide

### EBS Snapshots Cleanup
Delete unused EBS snapshots to save on storage costs.

```bash
# Basic usage
python3 snapshot_cleanup.py

# Use specific AWS profile
python3 snapshot_cleanup.py --profile dev
```

**Cost Impact**: ~$0.05/GB-month  
**Typical Savings**: $50-200/month  

**Sample Output:**
```
SNAPSHOT SUMMARY
================================================================================
Total snapshots found: 25
Total storage size: 850 GB
Estimated monthly savings: $42.50

Do you want to DELETE ALL 25 snapshots? (y/n):
```

### EBS Volumes Cleanup
Delete unattached EBS volumes (safely skips volumes attached to running instances).

```bash
# Basic usage
python3 volume_cleanup.py --profile production

# Show help
python3 volume_cleanup.py --help
```

**Cost Impact**: $0.08-0.30/GB-month (varies by volume type)  
**Typical Savings**: $100-500/month  

**Sample Output:**
```
VOLUME SUMMARY
================================================================================
Total volumes found: 45
Available (unattached) volumes: 12
Potential monthly savings: $156.80

⚠️  WARNING: You are about to delete 12 available volumes
```

### S3 Buckets Cleanup
Delete S3 buckets and all their contents with intelligent safety warnings.

```bash
# ALWAYS start with dry-run for S3!
python3 s3_cleanup.py --dry-run --profile dev

# Run for real after reviewing dry-run
python3 s3_cleanup.py --profile dev
```

**Cost Impact**: ~$0.023/GB-month + request costs  
**Typical Savings**: $50-1000/month  

**Features:**
- Handles versioned objects automatically
- Batch deletion for efficiency  
- Safety warnings for important bucket names

### Lambda Functions Cleanup
Delete unused Lambda functions and reduce clutter.

```bash
# Basic usage
python3 lambda_cleanup.py

# Dry-run mode
python3 lambda_cleanup.py --dry-run --profile staging
```

**Cost Impact**: $0.20 per 1M requests + GB-seconds  
**Typical Savings**: $20-100/month  

**Features:**
- Shows invocation statistics from last 30 days
- Identifies unused functions (0 invocations)
- Safety warnings for functions with event sources

### Load Balancer Cleanup
Delete unused Application, Network, and Classic Load Balancers.

```bash
# Basic usage
python3 loadbalancer_cleanup.py

# Target only Classic Load Balancers
python3 loadbalancer_cleanup.py --profile dev
# Then select 'clb' option
```

**Cost Impact**: $18-22/month per load balancer  
**Typical Savings**: $100-2000/month  

**Features:**
- Supports ALB, NLB, and CLB
- Shows target health status
- Identifies unused load balancers with no traffic

### RDS Database Cleanup
Delete unused RDS instances and Aurora clusters - **HIGHEST COST IMPACT**.

```bash
# ALWAYS start with dry-run for RDS!
python3 rds_cleanup.py --dry-run

# Run carefully after review
python3 rds_cleanup.py --profile production
```

**Cost Impact**: $50-500+/month per database  
**Typical Savings**: $200-5000/month  

**Features:**
- Handles both RDS instances and Aurora clusters
- Shows connection activity metrics
- Optional final snapshots for recovery
- Safety warnings for production databases

### ElastiCache Cleanup
Delete unused Redis and Memcached clusters.

```bash
# Basic usage
python3 elasticache_cleanup.py

# Target only Memcached clusters
python3 elasticache_cleanup.py --profile dev
# Then select 'memcached' option
```

**Cost Impact**: $20-200/month per cluster  
**Typical Savings**: $100-2000/month  

**Features:**
- Supports both Redis and Memcached
- Handles replication groups correctly
- Shows connection and cache hit metrics

### KMS Keys Cleanup
Delete unused customer-managed KMS keys.

```bash
# Basic usage
python3 kms_cleanup.py

# Dry-run mode
python3 kms_cleanup.py --dry-run --profile dev
```

**Cost Impact**: $1/month per key  
**Typical Savings**: $10-100/month  

**Features:**
- Only targets customer-managed keys (not AWS-managed)
- Shows key usage from CloudTrail
- Configurable pending deletion window (7-30 days)
- Safety warnings for keys used by AWS services

### Secrets Manager Cleanup
Delete unused secrets to reduce costs and security exposure.

```bash
# Basic usage
python3 secrets_cleanup.py

# Target only user-managed secrets
python3 secrets_cleanup.py --profile staging
# Then select 'user' option
```

**Cost Impact**: $0.40/month per secret  
**Typical Savings**: $10-200/month  

**Features:**
- Shows rotation status and version count
- Identifies unused secrets with no recent access
- Configurable recovery window (7-30 days)
- Safety warnings for AWS-managed secrets

### EFS File Systems Cleanup
Delete unused Elastic File Systems.

```bash
# Basic usage with dry-run (recommended)
python3 efs_cleanup.py --dry-run

# Run for real
python3 efs_cleanup.py --profile production
```

**Cost Impact**: ~$0.30/GB-month for standard storage  
**Typical Savings**: $50-500/month  

**Features:**
- Automatically deletes mount targets and access points
- Shows I/O activity metrics
- Safety warnings for mounted file systems
- Handles both Regional and One Zone file systems

### EKS Clusters Cleanup
Delete unused Kubernetes clusters - **VERY HIGH COST IMPACT**.

```bash
# ALWAYS start with dry-run for EKS!
python3 eks_cleanup.py --dry-run

# Use with extreme caution
python3 eks_cleanup.py --profile dev
```

**Cost Impact**: $72/month per cluster + worker node costs  
**Typical Savings**: $200-5000/month  

**Features:**
- Automatically deletes node groups and Fargate profiles
- Shows estimated worker node costs
- Safety warnings for clusters with workloads
- Handles add-ons deletion properly

## 💰 Cost Savings Examples

### Real-World Scenarios

#### Startup Cleanup (3-month-old account)
```
Service               | Before    | After     | Monthly Savings
EBS Snapshots        | $85.00    | $5.00     | $80.00
Unused Volumes       | $240.00   | $45.00    | $195.00
Old S3 Buckets       | $120.00   | $15.00    | $105.00
Test Load Balancers  | $88.00    | $22.00    | $66.00
Development RDS      | $380.00   | $76.00    | $304.00
Total Monthly        | $913.00   | $163.00   | $750.00
Annual Savings       |           |           | $9,000.00
```

#### Enterprise Cleanup (2-year-old account)
```
Service               | Before      | After       | Monthly Savings
EBS Snapshots        | $450.00     | $50.00      | $400.00
Unused Volumes       | $1,200.00   | $200.00     | $1,000.00
S3 Buckets           | $800.00     | $120.00     | $680.00
Unused Load Balancers| $440.00     | $88.00      | $352.00
Test/Dev RDS         | $2,300.00   | $460.00     | $1,840.00
Unused ElastiCache   | $600.00     | $100.00     | $500.00
Old EKS Clusters     | $1,440.00   | $288.00     | $1,152.00
KMS Keys             | $127.00     | $25.00      | $102.00
Secrets Manager      | $84.00      | $16.00      | $68.00
EFS File Systems     | $320.00     | $40.00      | $280.00
Total Monthly        | $7,761.00   | $1,387.00   | $6,374.00
Annual Savings       |             |             | $76,488.00
```

### Cost by Service Type

| Service Type | Cost Range | Cleanup Frequency | ROI Timeline |
|--------------|------------|------------------|--------------|
| **RDS/Aurora** | $50-500/month each | Monthly | Immediate |
| **EKS Clusters** | $72+/month each | Quarterly | Immediate |
| **Load Balancers** | $18-22/month each | Monthly | Immediate |
| **ElastiCache** | $20-200/month each | Monthly | 1 week |
| **EBS Volumes** | $0.08-0.30/GB | Weekly | Immediate |
| **S3 Storage** | $0.023/GB | Monthly | 1 month |
| **EBS Snapshots** | $0.05/GB | Bi-weekly | Immediate |
| **EFS Storage** | $0.30/GB | Monthly | Immediate |
| **Lambda Functions** | Variable | Quarterly | 1 month |
| **KMS Keys** | $1/month each | Quarterly | 1 month |
| **Secrets Manager** | $0.40/month each | Quarterly | 1 month |

## 🔧 Advanced Usage

### Automated Cleanup Pipeline

Create a cleanup routine for regular cost optimization:

```bash
#!/bin/bash
# weekly_cleanup.sh

PROFILE="production"
LOG_DIR="./cleanup_logs"
DATE=$(date +%Y%m%d)

mkdir -p $LOG_DIR

echo "Starting weekly AWS cleanup - $(date)"

# Safe, high-impact cleanups
echo "Cleaning up EBS snapshots..."
python3 snapshot_cleanup.py --profile $PROFILE 2>&1 | tee $LOG_DIR/snapshots_$DATE.log

echo "Cleaning up unattached volumes..."
python3 volume_cleanup.py --profile $PROFILE 2>&1 | tee $LOG_DIR/volumes_$DATE.log

echo "Cleaning up unused Lambda functions..."
python3 lambda_cleanup.py --profile $PROFILE 2>&1 | tee $LOG_DIR/lambda_$DATE.log

# High-risk cleanups (run with caution)
echo "Checking for unused load balancers..."
python3 loadbalancer_cleanup.py --dry-run --profile $PROFILE 2>&1 | tee $LOG_DIR/lb_analysis_$DATE.log

echo "Weekly cleanup completed - $(date)"
```

### Profile-Based Cleanup

Different cleanup strategies for different environments:

```bash
# Development environment - aggressive cleanup
python3 rds_cleanup.py --profile dev
python3 eks_cleanup.py --profile dev  
python3 s3_cleanup.py --profile dev

# Staging environment - moderate cleanup
python3 snapshot_cleanup.py --profile staging
python3 volume_cleanup.py --profile staging
python3 lambda_cleanup.py --profile staging

# Production environment - conservative cleanup
python3 snapshot_cleanup.py --profile prod
python3 volume_cleanup.py --profile prod
# RDS and EKS - dry-run only!
python3 rds_cleanup.py --dry-run --profile prod
```

## 🚨 Safety Guidelines

### ⚠️ CRITICAL SAFETY REMINDERS

1. **IRREVERSIBLE ACTIONS** - Deleted resources cannot be recovered (except from snapshots)
2. **TEST FIRST** - Always run scripts on test accounts before production  
3. **USE DRY-RUN** - Use `--dry-run` for S3, RDS, EKS, and EFS cleanup first
4. **BACKUP CRITICAL DATA** - Ensure important data is backed up elsewhere
5. **UNDERSTAND DEPENDENCIES** - Check if resources are used by applications
6. **START SMALL** - Delete a few resources first, then scale up

### 🔐 Security Best Practices

1. **Principle of Least Privilege** - Only grant necessary permissions
2. **Use Temporary Credentials** - Consider AWS STS for temporary access
3. **Enable CloudTrail** - Log all deletion activities for audit
4. **Multi-Factor Authentication** - Use MFA for accounts with deletion permissions
5. **Regular Access Review** - Audit who has cleanup permissions

### 🚦 Risk Assessment by Service

| Risk Level | Services | Recommendation |
|------------|----------|----------------|
| **🟢 Low Risk** | EBS Snapshots, Unused EBS Volumes, KMS Keys | Safe to automate |
| **🟡 Medium Risk** | Lambda Functions, Unused Load Balancers, Secrets Manager | Manual review recommended |
| **🟠 High Risk** | S3 Buckets, ElastiCache, EFS | Always use dry-run first |
| **🔴 Critical Risk** | RDS Databases, EKS Clusters | Expert review required |

## 🛠️ Troubleshooting

### Common Issues

#### "No accessible regions found"
```bash
# Test your AWS connectivity
aws sts get-caller-identity
aws ec2 describe-regions --region us-east-1

# Check your network/proxy settings
echo $https_proxy
aws configure list
```

#### "AWS credentials not found"
```bash
# Configure AWS CLI
aws configure

# Check existing profiles
aws configure list-profiles

# Test specific profile
aws sts get-caller-identity --profile your-profile
```

#### "Access Denied" errors
- Verify IAM permissions match the prerequisites
- Check if you're using the correct AWS profile
- Ensure your user/role has sufficient permissions
- Try with different profile: `--profile admin`

#### Script appears stuck
- **S3 analysis** can take time for buckets with many objects
- **Large resource lists** take time to process
- **Network connectivity** issues to AWS regions
- Check CloudWatch for AWS API throttling

#### "TLS handshake timeout" errors
```bash
# Test specific region connectivity
curl -I https://ec2.us-east-1.amazonaws.com/
curl -I https://s3.us-east-1.amazonaws.com/

# Use accessible regions only
python3 script_name.py --profile your-profile
# Script will automatically skip inaccessible regions
```

#### Resource deletion fails

**EBS Volumes:**
```bash
# Check if volume is attached
aws ec2 describe-volumes --volume-ids vol-12345 --profile your-profile

# Detach if needed
aws ec2 detach-volume --volume-id vol-12345 --profile your-profile
```

**S3 Buckets:**
```bash
# Check bucket policy and public access
aws s3api get-bucket-policy --bucket bucket-name --profile your-profile
aws s3api get-public-access-block --bucket bucket-name --profile your-profile
```

**RDS Instances:**
```bash
# Check for deletion protection
aws rds describe-db-instances --db-instance-identifier mydb --profile your-profile

# Disable deletion protection if needed
aws rds modify-db-instance --db-instance-identifier mydb --no-deletion-protection --profile your-profile
```

### Debug Mode

Add debug output to any script:
```python
# Add this at the top of the script after imports
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Performance Optimization

For large AWS accounts:
```bash
# Process one region at a time
export AWS_DEFAULT_REGION=us-east-1
python3 script_name.py --profile your-profile

# Use multiple terminals for parallel processing
# Terminal 1: US regions
# Terminal 2: EU regions  
# Terminal 3: APAC regions
```

## 📈 Best Practices

### Before Running Scripts

1. **Cost Analysis** - Review AWS Cost Explorer for biggest cost drivers
2. **Resource Inventory** - Use AWS Config or AWS Systems Manager for inventory
3. **Tag Strategy** - Implement consistent tagging for easier identification
4. **Backup Strategy** - Ensure critical data has proper backups
5. **Team Communication** - Notify team members before cleanup activities

### During Cleanup

1. **Start Conservative** - Begin with obviously unused resources
2. **Use Dry-Run Mode** - Always test destructive operations first
3. **Small Batches** - Process resources in small groups
4. **Monitor Impact** - Watch application performance during cleanup
5. **Document Changes** - Keep records of what was deleted

### After Cleanup

1. **Monitor Costs** - Check AWS Cost Explorer for savings verification
2. **Application Testing** - Verify applications still function correctly
3. **Update Documentation** - Document infrastructure changes
4. **Implement Governance** - Set up policies to prevent resource sprawl
5. **Schedule Regular Cleanup** - Make cleanup a recurring activity

### Cleanup Schedule Recommendations

| Service | Frequency | Best Day | Automation Level |
|---------|-----------|----------|------------------|
| EBS Snapshots | Weekly | Friday | High |
| EBS Volumes | Weekly | Friday | Medium |
| Lambda Functions | Monthly | Month-end | Medium |
| Load Balancers | Monthly | Friday | Low |
| S3 Buckets | Monthly | Saturday | Low |
| RDS Databases | Quarterly | Saturday | Manual Only |
| ElastiCache | Monthly | Friday | Low |
| KMS Keys | Quarterly | Month-end | Low |
| Secrets Manager | Quarterly | Month-end | Low |
| EFS File Systems | Monthly | Saturday | Manual Only |
| EKS Clusters | On-demand | Saturday | Manual Only |

## 🤝 Contributing & Support

### Reporting Issues

If you encounter problems:

1. **Check Prerequisites** - Ensure all requirements are met
2. **Try Dry-Run Mode** - Use `--dry-run` to identify issues
3. **Verify Permissions** - Confirm IAM permissions are correct
4. **Test Connectivity** - Check network access to AWS regions
5. **Collect Debug Info** - Include error messages and account region

### Common Feature Requests

**Planned Enhancements:**
- Additional resource types (NAT Gateways, Elastic IPs, etc.)
- Cost optimization recommendations
- Integration with AWS Cost Explorer
- CloudFormation template cleanup
- Automated scheduling with Lambda
- Slack/Teams integration for notifications
- Multi-account cleanup support

### Safety Disclaimer

⚠️ **IMPORTANT**: These scripts perform irreversible deletions that can result in:
- **Data Loss** - Permanent destruction of data and configurations
- **Service Disruption** - Applications may stop working if dependencies are deleted
- **Financial Impact** - While designed to save money, incorrect usage could disrupt services
- **Security Impact** - Deleting security resources could affect system security

**Use at your own risk** and always:
- Test on non-production accounts first
- Understand what each resource does before deleting it
- Have proper backups of critical data
- Review all safety warnings carefully

## ⚡ Quick Start Checklist

### Initial Setup
- [ ] Install Python 3.7+
- [ ] Install boto3: `pip install boto3`
- [ ] Configure AWS CLI: `aws configure`  
- [ ] Test credentials: `aws sts get-caller-identity`
- [ ] Download all scripts
- [ ] Make scripts executable: `chmod +x *.py`

### Safety Setup
- [ ] **CRITICAL**: Start with non-production AWS account
- [ ] Enable CloudTrail for audit logging
- [ ] Set up proper IAM permissions
- [ ] Create test resources to verify script behavior
- [ ] Review all safety warnings in this README

### First Cleanup (Recommended Order)
1. [ ] **EBS Snapshots**: `python3 snapshot_cleanup.py --profile test`
2. [ ] **EBS Volumes**: `python3 volume_cleanup.py --profile test`
3. [ ] **Lambda Functions**: `python3 lambda_cleanup.py --profile test`
4. [ ] **S3 Buckets**: `python3 s3_cleanup.py --dry-run --profile test`
5. [ ] **Load Balancers**: `python3 loadbalancer_cleanup.py --dry-run --profile test`

### Monitor and Expand
- [ ] Check AWS Cost Explorer for savings verification
- [ ] Test applications to ensure no impact
- [ ] Gradually expand to higher-risk services
- [ ] Set up regular cleanup schedule
- [ ] Document your cleanup process

---

**📞 Remember: These scripts can save you thousands of dollars per year, but they delete resources permanently. Always understand what you're deleting and test thoroughly on non-production accounts first.**

**💡 Pro Tip: Start with EBS snapshots and unused volumes for immediate, safe savings, then gradually work up to more complex services like RDS and EKS.**