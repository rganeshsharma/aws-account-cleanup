#!/usr/bin/env python3
"""
AWS Secrets Manager Cleanup Tool
Lists all secrets and allows safe deletion with cost analysis.
Secrets Manager costs $0.40/month per secret plus API calls, can accumulate with old secrets.
"""

import boto3
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
import time
import json

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    BOLD = '\033[1m'
    END = '\033[0m'

class SecretsManagerCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS Secrets Manager cleaner"""
        self.profile_name = profile_name
        self.session = None
        self.accessible_regions = []
        self.setup_aws_session()
        
    def setup_aws_session(self):
        """Setup AWS session with the specified profile"""
        try:
            if self.profile_name:
                self.session = boto3.Session(profile_name=self.profile_name)
                print(f"{Colors.BLUE}Using AWS profile: {self.profile_name}{Colors.END}")
            else:
                self.session = boto3.Session()
                print(f"{Colors.BLUE}Using default AWS profile{Colors.END}")
            
            # Test credentials
            sts = self.session.client('sts')
            identity = sts.get_caller_identity()
            
            print(f"{Colors.GREEN}✓ Connected to AWS Account: {identity['Account']}{Colors.END}")
            print(f"{Colors.GREEN}✓ User/Role: {identity['Arn']}{Colors.END}")
            
        except NoCredentialsError:
            print(f"{Colors.RED}Error: AWS credentials not found!{Colors.END}")
            print("Please run: aws configure")
            sys.exit(1)
        except ClientError as e:
            print(f"{Colors.RED}Error: {e}{Colors.END}")
            sys.exit(1)
    
    def test_region_connectivity(self) -> List[str]:
        """Test connectivity to different AWS regions"""
        test_regions = [
            'us-east-1', 'us-west-2', 'ap-south-1', 
            'ap-southeast-1', 'eu-west-1', 'eu-central-1'
        ]
        
        accessible_regions = []
        print(f"\n{Colors.BLUE}Testing region connectivity...{Colors.END}")
        
        for region in test_regions:
            try:
                secrets = self.session.client('secretsmanager', region_name=region)
                secrets.list_secrets(MaxResults=1)
                print(f"{Colors.GREEN}✓ {region} - accessible{Colors.END}")
                accessible_regions.append(region)
            except (EndpointConnectionError, ClientError) as e:
                print(f"{Colors.RED}✗ {region} - not accessible{Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}✗ {region} - error: {str(e)[:50]}...{Colors.END}")
        
        if not accessible_regions:
            print(f"{Colors.RED}Error: No accessible regions found!{Colors.END}")
            sys.exit(1)
            
        self.accessible_regions = accessible_regions
        return accessible_regions
    
    def get_secret_usage_stats(self, secret_arn: str, region: str) -> Dict[str, Any]:
        """Get usage statistics for a secret from CloudTrail"""
        try:
            cloudtrail = self.session.client('cloudtrail', region_name=region)
            
            # Look for secret usage in the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            # Search for events related to this secret
            events = cloudtrail.lookup_events(
                LookupAttributes=[
                    {
                        'AttributeKey': 'ResourceName',
                        'AttributeValue': secret_arn
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                MaxItems=50
            )
            
            usage_events = []
            for event in events.get('Events', []):
                event_name = event.get('EventName', '')
                if event_name in ['GetSecretValue', 'UpdateSecret', 'PutSecretValue']:
                    usage_events.append({
                        'event_name': event_name,
                        'event_time': event['EventTime'],
                        'source_ip': event.get('SourceIPAddress', 'Unknown')
                    })
            
            return {
                'total_usage_events': len(usage_events),
                'last_used': max([event['event_time'] for event in usage_events]) if usage_events else None,
                'has_recent_usage': len(usage_events) > 0
            }
            
        except ClientError as e:
            # CloudTrail might not be available or configured
            return {
                'total_usage_events': 0,
                'last_used': None,
                'has_recent_usage': False,
                'error': str(e)
            }
    
    def get_secret_versions(self, secret_arn: str, region: str) -> Dict[str, Any]:
        """Get version information for a secret"""
        try:
            secrets = self.session.client('secretsmanager', region_name=region)
            
            versions = secrets.list_secret_version_ids(SecretId=secret_arn)
            
            version_count = len(versions.get('Versions', []))
            current_version = None
            pending_version = None
            
            for version in versions.get('Versions', []):
                version_stages = version.get('VersionStages', [])
                if 'AWSCURRENT' in version_stages:
                    current_version = version['VersionId']
                if 'AWSPENDING' in version_stages:
                    pending_version = version['VersionId']
            
            return {
                'version_count': version_count,
                'current_version': current_version,
                'pending_version': pending_version,
                'has_pending_version': pending_version is not None
            }
            
        except ClientError:
            return {
                'version_count': 0,
                'current_version': None,
                'pending_version': None,
                'has_pending_version': False
            }
    
    def check_secret_safety(self, secret_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if secret appears to be important or in use"""
        secret_name = secret_info['name']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary',
            'database', 'db', 'api', 'oauth', 'jwt', 'ssl', 'tls'
        ]
        
        name_lower = secret_name.lower()
        for pattern in important_patterns:
            if pattern in name_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
                break
        
        # Check if secret has recent usage
        if secret_info.get('usage_stats', {}).get('has_recent_usage'):
            usage_count = secret_info['usage_stats']['total_usage_events']
            safety_warnings.append(f"Recent usage: {usage_count} events in 30 days")
        
        # Check if secret is managed by AWS service
        if secret_info.get('managed_by'):
            safety_warnings.append(f"Managed by AWS service: {secret_info['managed_by']}")
        
        # Check if secret has automatic rotation
        if secret_info.get('rotation_enabled'):
            safety_warnings.append("Automatic rotation is enabled")
        
        # Check if secret has multiple versions (indicates active use)
        version_info = secret_info.get('version_info', {})
        if version_info.get('version_count', 0) > 1:
            safety_warnings.append(f"Has {version_info['version_count']} versions")
        
        if version_info.get('has_pending_version'):
            safety_warnings.append("Has pending version (rotation in progress)")
        
        # Check if secret has replica regions
        if secret_info.get('replica_regions'):
            replica_count = len(secret_info['replica_regions'])
            safety_warnings.append(f"Replicated to {replica_count} regions")
        
        # Check if recently created (within 7 days)
        created_time = secret_info['created_date']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        # Check if recently accessed
        last_accessed = secret_info.get('last_accessed_date')
        if last_accessed:
            days_since_accessed = (datetime.now(timezone.utc) - last_accessed).days
            if days_since_accessed <= 7:
                safety_warnings.append(f"Recently accessed ({days_since_accessed} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def list_secrets_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all secrets in a specific region"""
        try:
            secrets_client = self.session.client('secretsmanager', region_name=region)
            
            secrets = []
            paginator = secrets_client.get_paginator('list_secrets')
            
            for page in paginator.paginate():
                for secret in page['SecretList']:
                    secret_arn = secret['ARN']
                    secret_name = secret['Name']
                    
                    # Skip secrets that are already deleted
                    if secret.get('DeletedDate'):
                        continue
                    
                    # Get detailed secret information
                    try:
                        secret_details = secrets_client.describe_secret(SecretId=secret_arn)
                    except ClientError:
                        # Skip secrets we can't access
                        continue
                    
                    # Get version information
                    version_info = self.get_secret_versions(secret_arn, region)
                    
                    # Get usage statistics
                    usage_stats = self.get_secret_usage_stats(secret_arn, region)
                    
                    # Calculate monthly cost
                    # Base cost: $0.40 per secret per month
                    # Additional cost for replica regions: $0.05 per replica per month
                    base_cost = 0.40
                    replica_cost = len(secret_details.get('ReplicationStatus', [])) * 0.05
                    monthly_cost = base_cost + replica_cost
                    
                    secret_info = {
                        'name': secret_name,
                        'arn': secret_arn,
                        'region': region,
                        'description': secret_details.get('Description', ''),
                        'created_date': secret_details['CreatedDate'],
                        'last_changed_date': secret_details.get('LastChangedDate'),
                        'last_accessed_date': secret_details.get('LastAccessedDate'),
                        'rotation_enabled': secret_details.get('RotationEnabled', False),
                        'rotation_lambda_arn': secret_details.get('RotationLambdaARN'),
                        'managed_by': secret_details.get('OwningService'),
                        'kms_key_id': secret_details.get('KmsKeyId'),
                        'replica_regions': [r['Region'] for r in secret_details.get('ReplicationStatus', [])],
                        'tags': secret_details.get('Tags', []),
                        'version_info': version_info,
                        'usage_stats': usage_stats,
                        'monthly_cost': monthly_cost
                    }
                    
                    # Add safety check
                    secret_info['safety'] = self.check_secret_safety(secret_info)
                    
                    secrets.append(secret_info)
            
            return secrets
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing secrets in {region}: {e}{Colors.END}")
            return []
    
    def format_secret_info(self, secret: Dict[str, Any]) -> str:
        """Format secret information for display"""
        name = secret['name'][:25] if len(secret['name']) > 25 else secret['name']
        region = secret['region']
        description = secret['description'][:20] if secret['description'] else 'No description'
        
        # Rotation status
        rotation = "✓" if secret['rotation_enabled'] else "✗"
        
        # Version count
        version_count = secret['version_info']['version_count']
        
        # Usage indicator
        usage_stats = secret['usage_stats']
        if usage_stats.get('has_recent_usage'):
            usage = f"{usage_stats['total_usage_events']} uses"
        else:
            usage = "No usage"
        
        # Last accessed
        last_accessed = secret.get('last_accessed_date')
        if last_accessed:
            days_ago = (datetime.now(timezone.utc) - last_accessed).days
            last_access = f"{days_ago}d ago"
        else:
            last_access = "Never"
        
        created_time = secret['created_date']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        
        monthly_cost = secret['monthly_cost']
        
        # Managed by AWS service indicator
        managed = "AWS" if secret.get('managed_by') else "User"
        
        # Safety indicator
        if secret['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {name:<25} | {region:<12} | {description:<20} | {rotation:<3} | {version_count:>2} | {usage:<10} | {last_access:<8} | {managed:<4} | ${monthly_cost:>4.2f} | {days_since_created:>3}d | {safety_indicator}"
    
    def list_all_secrets(self) -> List[Dict[str, Any]]:
        """List all secrets across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*160}{Colors.END}")
        print(f"{Colors.BLUE}Scanning AWS Secrets Manager across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*160}{Colors.END}")
        
        all_secrets = []
        total_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            secrets = self.list_secrets_in_region(region)
            
            if secrets:
                region_cost = sum(secret['monthly_cost'] for secret in secrets)
                
                rotation_enabled_count = sum(1 for secret in secrets if secret['rotation_enabled'])
                aws_managed_count = sum(1 for secret in secrets if secret.get('managed_by'))
                
                print(f"{Colors.GREEN}Found {len(secrets)} secrets{Colors.END}")
                print(f"  Rotation enabled: {rotation_enabled_count}")
                print(f"  AWS managed: {aws_managed_count}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                all_secrets.extend(secrets)
            else:
                print(f"{Colors.GREEN}No secrets found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for secret in all_secrets if secret['safety']['is_risky'])
        unused_count = sum(1 for secret in all_secrets if not secret['usage_stats'].get('has_recent_usage', False))
        aws_managed_count = sum(1 for secret in all_secrets if secret.get('managed_by'))
        
        print(f"\n{Colors.BOLD}SECRETS MANAGER SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*160}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total secrets found: {Colors.YELLOW}{len(all_secrets)}{Colors.END}")
        print(f"Secrets with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused secrets (no recent access): {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"AWS-managed secrets: {Colors.BLUE}{aws_managed_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_secrets:
            print(f"\n{Colors.BOLD}SECRET DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*160}{Colors.END}")
            print(f"  {'Secret Name':<25} | {'Region':<12} | {'Description':<20} | {'Rot':<3} | {'Ver':<2} | {'Usage':<10} | {'LastAcc':<8} | {'Mgmt':<4} | {'Cost':<5} | {'Age':<4} | Safe")
            print(f"  {'-'*25} | {'-'*12} | {'-'*20} | {'-'*3} | {'-'*2} | {'-'*10} | {'-'*8} | {'-'*4} | {'-'*5} | {'-'*4} | {'-'*4}")
            
            # Sort by safety risk (risky first), then by cost (highest first)
            sorted_secrets = sorted(all_secrets, key=lambda x: (not x['safety']['is_risky'], -x['monthly_cost']))
            
            for secret in sorted_secrets:
                print(self.format_secret_info(secret))
                
                # Show safety warnings
                if secret['safety']['warnings']:
                    for warning in secret['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by management type
            print(f"\n{Colors.BOLD}BREAKDOWN BY MANAGEMENT TYPE{Colors.END}")
            user_managed = [s for s in all_secrets if not s.get('managed_by')]
            aws_managed = [s for s in all_secrets if s.get('managed_by')]
            
            if user_managed:
                user_cost = sum(s['monthly_cost'] for s in user_managed)
                print(f"  User-managed: {len(user_managed)} secrets, ${user_cost:.2f}/month")
            
            if aws_managed:
                aws_cost = sum(s['monthly_cost'] for s in aws_managed)
                print(f"  AWS-managed : {len(aws_managed)} secrets, ${aws_cost:.2f}/month")
        
        return all_secrets
    
    def get_user_confirmation(self, message: str) -> bool:
        """Get user confirmation"""
        while True:
            response = input(f"\n{Colors.YELLOW}{message} (y/n): {Colors.END}").lower().strip()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print(f"{Colors.RED}Please enter 'y' for yes or 'n' for no{Colors.END}")
    
    def show_secret_selection_menu(self, secrets: List[Dict[str, Any]]) -> List[str]:
        """Show menu for secret selection"""
        if not secrets:
            return []
        
        print(f"\n{Colors.BOLD}SELECT SECRETS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter secret numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all secrets")
        print("Or enter 'unused' to select secrets with no recent usage")
        print("Or enter 'user' to select only user-managed secrets")
        print("Or enter 'safe' to select only secrets without warnings")
        print("")
        
        # Show numbered list
        unused_secrets = []
        safe_secrets = []
        user_managed_secrets = []
        
        for i, secret in enumerate(secrets, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if secret['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            monthly_cost = secret['monthly_cost']
            
            # Truncate display for readability
            description = secret['description'][:30] if secret['description'] else 'No description'
            
            usage_indicator = ""
            if not secret['usage_stats'].get('has_recent_usage', False):
                usage_indicator = f"{Colors.YELLOW}(UNUSED){Colors.END}"
                unused_secrets.append(secret['name'])
            
            if not secret.get('managed_by'):
                user_managed_secrets.append(secret['name'])
            
            if not secret['safety']['is_risky']:
                safe_secrets.append(secret['name'])
            
            managed_by = secret.get('managed_by', 'User')
            
            print(f"{i:2d}. {secret['name']:<30} | {secret['region']:<12} | {description:<30} | {managed_by:<10} | ${monthly_cost:>4.2f}/mo | {safety_indicator} {usage_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [secret['name'] for secret in secrets]
            elif choice == 'unused':
                if unused_secrets:
                    return unused_secrets
                else:
                    print(f"{Colors.RED}No unused secrets found{Colors.END}")
                    continue
            elif choice == 'user':
                if user_managed_secrets:
                    return user_managed_secrets
                else:
                    print(f"{Colors.RED}No user-managed secrets found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_secrets:
                    return safe_secrets
                else:
                    print(f"{Colors.RED}No 'safe' secrets found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(secrets):
                            selected.append(secrets[idx-1]['name'])
                        else:
                            print(f"{Colors.RED}Invalid secret number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'unused', 'user', or 'safe'{Colors.END}")
    
    def delete_secret(self, secret: Dict[str, Any], force_delete: bool = False, recovery_window_days: int = 7, dry_run: bool = False) -> bool:
        """Delete a secret"""
        secret_name = secret['name']
        region = secret['region']
        
        if dry_run:
            action_text = "immediately" if force_delete else f"with {recovery_window_days} day recovery window"
            print(f"  {Colors.BLUE}[DRY RUN] Would delete secret {secret_name} {action_text}{Colors.END}")
            return True
        
        try:
            secrets_client = self.session.client('secretsmanager', region_name=region)
            
            if force_delete:
                # Immediate deletion (cannot be recovered)
                secrets_client.delete_secret(
                    SecretId=secret_name,
                    ForceDeleteWithoutRecovery=True
                )
            else:
                # Schedule for deletion with recovery window
                secrets_client.delete_secret(
                    SecretId=secret_name,
                    RecoveryWindowInDays=recovery_window_days
                )
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                print(f"  {Colors.YELLOW}Secret {secret_name} not found (already deleted?){Colors.END}")
                return True
            elif error_code == 'InvalidRequestException':
                if 'scheduled for deletion' in str(e):
                    print(f"  {Colors.YELLOW}Secret {secret_name} is already scheduled for deletion{Colors.END}")
                    return True
                else:
                    print(f"  {Colors.RED}Invalid request for {secret_name}: {e}{Colors.END}")
            else:
                print(f"  {Colors.RED}Error deleting {secret_name}: {e}{Colors.END}")
            return False
    
    def delete_secrets(self, secrets: List[Dict[str, Any]], selected_secret_names: List[str], force_delete: bool = False, recovery_window_days: int = 7, dry_run: bool = False):
        """Delete selected secrets"""
        secrets_to_delete = [secret for secret in secrets if secret['name'] in selected_secret_names]
        
        if not secrets_to_delete:
            print(f"{Colors.YELLOW}No secrets selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING SECRETS MANAGER SECRETS{Colors.END}")
        if not dry_run:
            if force_delete:
                print(f"{Colors.RED}IMMEDIATE DELETION - CANNOT BE RECOVERED!{Colors.END}")
            else:
                print(f"{Colors.RED}Scheduled for deletion with {recovery_window_days} day recovery window{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, secret in enumerate(secrets_to_delete, 1):
            secret_name = secret['name']
            region = secret['region']
            description = secret['description'] or 'No description'
            monthly_cost = secret['monthly_cost']
            
            print(f"\n[{i}/{len(secrets_to_delete)}] Processing secret: {secret_name}")
            print(f"  Description: {description}")
            print(f"  Region: {region}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if secret['safety']['warnings']:
                for warning in secret['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_secret(secret, force_delete, recovery_window_days, dry_run):
                action_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {action_text} {secret_name}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {secret_name}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            if not dry_run:
                time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        action_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {action_text}: {Colors.GREEN}{deleted_count} secrets{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} secrets{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            if force_delete:
                print(f"\n{Colors.RED}Warning: Secrets were immediately deleted and cannot be recovered!{Colors.END}")
            else:
                print(f"\n{Colors.YELLOW}Important Notes:{Colors.END}")
                print(f"• Secrets are scheduled for deletion in {recovery_window_days} days")
                print(f"• You can restore them during the recovery window")
                print(f"• Use 'aws secretsmanager restore-secret --secret-id <name>' to restore")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS Secrets Manager Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all secrets
        secrets = self.list_all_secrets()
        
        if not secrets:
            print(f"\n{Colors.GREEN}No secrets found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(secret['monthly_cost'] for secret in secrets)
        risky_count = sum(1 for secret in secrets if secret['safety']['is_risky'])
        unused_count = sum(1 for secret in secrets if not secret['usage_stats'].get('has_recent_usage', False))
        aws_managed_count = sum(1 for secret in secrets if secret.get('managed_by'))
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total secrets: {Colors.BLUE}{len(secrets)}{Colors.END}")
        print(f"Secrets with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused secrets (no recent access): {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"AWS-managed secrets: {Colors.BLUE}{aws_managed_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  Secret deletion may affect applications using them!{Colors.END}")
            print(f"{Colors.RED}⚠️  Consider recovery window for safety!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with secret selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select secrets
        selected_secret_names = self.show_secret_selection_menu(secrets)
        
        if not selected_secret_names:
            print(f"{Colors.BLUE}No secrets selected. Exiting.{Colors.END}")
            return
        
        selected_secrets = [secret for secret in secrets if secret['name'] in selected_secret_names]
        selected_cost = sum(secret['monthly_cost'] for secret in selected_secrets)
        
        # Ask about deletion options
        force_delete = False
        recovery_window_days = 7
        
        if not dry_run:
            print(f"\n{Colors.YELLOW}DELETION OPTIONS{Colors.END}")
            print("Secrets can be deleted immediately or scheduled with a recovery window.")
            print("Recovery window allows restoration if deletion was accidental.")
            
            force_delete = self.get_user_confirmation("Delete immediately without recovery window? (not recommended)")
            
            if not force_delete:
                while True:
                    try:
                        days_input = input(f"Enter recovery window days (7-30, default 7): ").strip()
                        if not days_input:
                            recovery_window_days = 7
                            break
                        
                        recovery_window_days = int(days_input)
                        if 7 <= recovery_window_days <= 30:
                            break
                        else:
                            print(f"{Colors.RED}Please enter a number between 7 and 30{Colors.END}")
                    except ValueError:
                        print(f"{Colors.RED}Please enter a valid number{Colors.END}")
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected secrets: {Colors.YELLOW}{len(selected_secrets)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            deletion_type = "Immediate deletion" if force_delete else f"Recovery window: {recovery_window_days} days"
            print(f"Deletion type: {Colors.YELLOW}{deletion_type}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you sure you want to delete these secrets?"
        if self.get_user_confirmation(final_question):
            self.delete_secrets(secrets, selected_secret_names, force_delete, recovery_window_days, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS Secrets Manager Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 secrets_cleanup.py                      # Use default AWS profile
  python3 secrets_cleanup.py --profile dev        # Use specific profile
  python3 secrets_cleanup.py --dry-run            # Test mode - no actual deletions
  
Features:
  - Lists all Secrets Manager secrets with usage analysis
  - Shows rotation status and version information
  - Identifies unused secrets with no recent access
  - Safety warnings for AWS-managed and active secrets
  - Cost impact: $0.40/month per secret plus API calls
  - Configurable recovery window for safe deletion
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help='AWS profile to use (default: uses default profile)'
    )
    
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Dry run mode - show what would be deleted without actually deleting'
    )
    
    args = parser.parse_args()
    
    try:
        cleaner = SecretsManagerCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()