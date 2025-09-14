# AWS Nuke Installation and Usage Guide

## ⚠️ **CRITICAL WARNING** ⚠️
**aws-nuke will DELETE ALL resources in your AWS account. Use with extreme caution and ONLY on accounts you're comfortable completely wiping clean.**

## What is aws-nuke?

aws-nuke is a tool that removes all resources from an AWS account. It's commonly used for:
- Cleaning up development/test environments
- Decommissioning AWS accounts
- Removing all traces of resources for compliance

## Step 1: Prerequisites

Before installing aws-nuke, ensure you have:

1. **AWS CLI installed and configured**
   ```bash
   # Install AWS CLI
   pip install awscli
   
   # Configure with your credentials
   aws configure
   ```

2. **Appropriate AWS permissions** (AdministratorAccess or equivalent)
3. **Go installed** (if building from source)

## Step 2: Installation Methods

### Method A: Download Pre-built Binary (Recommended)

1. **Go to the releases page:**
   ```bash
   # Visit: https://github.com/rebuy-de/aws-nuke/releases
   ```

2. **Download the appropriate binary for your system:**
   ```bash
   # For Linux x64
   wget https://github.com/rebuy-de/aws-nuke/releases/download/v2.25.0/aws-nuke-v2.25.0-linux-amd64.tar.gz
   
   # For macOS
   wget https://github.com/rebuy-de/aws-nuke/releases/download/v2.25.0/aws-nuke-v2.25.0-darwin-amd64.tar.gz
   
   # For Windows
   wget https://github.com/rebuy-de/aws-nuke/releases/download/v2.25.0/aws-nuke-v2.25.0-windows-amd64.tar.gz
   ```

3. **Extract and install:**
   ```bash
   # Extract the archive
   tar -xzf aws-nuke-v2.25.0-linux-amd64.tar.gz
   
   # Move to a directory in your PATH
   sudo mv aws-nuke /usr/local/bin/
   
   # Make it executable
   chmod +x /usr/local/bin/aws-nuke
   ```

### Method B: Build from Source

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rebuy-de/aws-nuke.git
   cd aws-nuke
   ```

2. **Build the binary:**
   ```bash
   make build
   ```

3. **Install:**
   ```bash
   sudo cp dist/aws-nuke /usr/local/bin/
   ```

### Method C: Using Go Install

```bash
go install github.com/rebuy-de/aws-nuke/v2@latest
```

## Step 3: Verify Installation

```bash
aws-nuke --version
```

## Step 4: Create Configuration File

Create a configuration file `config.yaml`:

```yaml
# config.yaml
regions:
  - us-east-1
  - us-west-2
  - eu-west-1
  # Add all regions you want to clean

account-blocklist:
  - "999999999999" # Add your production account IDs to prevent accidental deletion

accounts:
  "123456789012": # Your target AWS account ID
    presets:
      - "terraform"
    filters:
      # Protect specific resources (optional)
      IAMRole:
        - "MyImportantRole"
      S3Bucket:
        - property: "Name"
          value: "my-important-bucket"
      EC2Instance:
        - property: "tag:Environment"
          value: "production"

presets:
  terraform:
    filters:
      S3Bucket:
        - property: "Name"
          type: "regex"
          value: "terraform-state-.*"
```

### Configuration Options Explained:

- **regions**: List of AWS regions to clean
- **account-blocklist**: Account IDs that should never be nuked (safety feature)
- **accounts**: Target account configuration
- **filters**: Resources to preserve (whitelist)
- **presets**: Reusable filter configurations

## Step 5: Test Run (Dry Run)

**Always perform a dry run first:**

```bash
aws-nuke -c config.yaml --profile my-aws-profile
```

This will show you what would be deleted without actually deleting anything.

## Step 6: Understanding the Output

The dry run will show:
- ✅ Resources that would be deleted
- 🛡️ Resources that would be filtered (preserved)
- ❌ Resources that failed to enumerate

Review this carefully before proceeding.

## Step 7: Execute the Deletion

**Only after you're satisfied with the dry run:**

```bash
aws-nuke -c config.yaml --profile my-aws-profile --no-dry-run
```

### Alternative execution options:

```bash
# Force deletion without confirmation prompts
aws-nuke -c config.yaml --no-dry-run --force

# Delete resources older than specific time
aws-nuke -c config.yaml --no-dry-run --older-than 24h

# Target specific resource types
aws-nuke -c config.yaml --no-dry-run --target EC2Instance,S3Bucket
```

## Step 8: Monitor Progress

aws-nuke will:
1. Scan all regions for resources
2. Show a summary of what will be deleted
3. Ask for confirmation (unless `--force` is used)
4. Delete resources in dependency order
5. Retry failed deletions
6. Provide a final summary

## Advanced Usage

### Custom Resource Filters

```yaml
accounts:
  "123456789012":
    filters:
      EC2Instance:
        - property: "tag:Name"
          value: "keep-this-instance"
        - property: "InstanceId"
          value: "i-1234567890abcdef0"
      
      S3Bucket:
        - property: "Name"
          type: "glob"
          value: "backup-*"
        - property: "CreationDate"
          type: "dateOlderThan"
          value: "2023-01-01"
```

### Environment-Specific Configuration

```yaml
# dev-config.yaml
regions:
  - us-east-1

accounts:
  "123456789012":
    filters:
      IAMRole:
        - "OrganizationAccountAccessRole"
      CloudFormationStack:
        - property: "Name"
          type: "regex"
          value: "CDKToolkit"
```

### Targeting Specific Resources

```bash
# Only delete EC2 instances and EBS volumes
aws-nuke -c config.yaml --target EC2Instance,EBSVolume --no-dry-run

# Exclude specific resource types
aws-nuke -c config.yaml --exclude IAMRole,IAMPolicy --no-dry-run
```

## Safety Best Practices

1. **Always use account-blocklist** for production accounts
2. **Test with dry-run first** - multiple times if needed
3. **Use filters** to preserve critical resources
4. **Backup important data** before running
5. **Run during maintenance windows** to avoid disruption
6. **Monitor AWS costs** to ensure resources are actually deleted
7. **Check CloudTrail logs** for audit trail

## Common Issues and Solutions

### Issue: "Account not in configuration"
```bash
# Solution: Add account ID to config.yaml accounts section
```

### Issue: "Access Denied" errors
```bash
# Solution: Ensure IAM user/role has sufficient permissions
# Required: AdministratorAccess or equivalent
```

### Issue: Resources not deleting
```bash
# Some resources have dependencies or deletion protection
# Run multiple times - aws-nuke will retry
aws-nuke -c config.yaml --no-dry-run --max-wait-retries 10
```

### Issue: Rate limiting
```bash
# Use delays between API calls
aws-nuke -c config.yaml --no-dry-run --sleep-between-resources 1s
```

## Example Complete Workflow

```bash
# 1. Verify AWS credentials
aws sts get-caller-identity

# 2. Create and review config
cat > nuke-config.yaml << 'EOF'
regions:
  - us-east-1
  - us-west-2

account-blocklist:
  - "111111111111"  # Production account

accounts:
  "123456789012":   # Dev/test account
    filters:
      IAMRole:
        - "OrganizationAccountAccessRole"
EOF

# 3. Dry run
aws-nuke -c nuke-config.yaml

# 4. Review output carefully

# 5. Execute if satisfied
aws-nuke -c nuke-config.yaml --no-dry-run

# 6. Monitor AWS console to verify deletion
```

## Alternative Tools to Consider

- **AWS CLI with scripts** - More granular control
- **Terraform destroy** - If resources are Terraform-managed  
- **AWS CDK destroy** - If resources are CDK-managed
- **Manual deletion** - For small numbers of resources

## Final Reminders

- 🚨 **This tool is destructive** - it will delete everything
- 💰 **Verify billing** - ensure resources are actually gone
- 📝 **Document what you're doing** - for audit purposes  
- 🔄 **Have a rollback plan** - in case you need to recreate resources
- 👥 **Communicate with team** - ensure no one else needs the resources