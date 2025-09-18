#!/usr/bin/env python3
"""
AWS KMS Keys Cleanup Tool
Lists all KMS customer-managed keys and allows safe deletion with cost analysis.
KMS keys cost $1/month each but can accumulate, and unused keys are a security risk.
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

class KMSCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS KMS cleaner"""
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
                kms = self.session.client('kms', region_name=region)
                kms.list_keys(Limit=1)
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
    
    def get_key_usage_stats(self, key_id: str, region: str) -> Dict[str, Any]:
        """Get usage statistics for a KMS key from CloudTrail"""
        try:
            cloudtrail = self.session.client('cloudtrail', region_name=region)
            
            # Look for KMS key usage in the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            # Search for events related to this key
            events = cloudtrail.lookup_events(
                LookupAttributes=[
                    {
                        'AttributeKey': 'ResourceName',
                        'AttributeValue': key_id
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                MaxItems=50
            )
            
            usage_events = []
            for event in events.get('Events', []):
                event_name = event.get('EventName', '')
                if event_name in ['Encrypt', 'Decrypt', 'GenerateDataKey', 'GenerateDataKeyWithoutPlaintext']:
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
    
    def get_key_aliases(self, key_id: str, region: str) -> List[str]:
        """Get aliases for a KMS key"""
        try:
            kms = self.session.client('kms', region_name=region)
            
            # List all aliases and find ones that point to this key
            aliases = []
            paginator = kms.get_paginator('list_aliases')
            
            for page in paginator.paginate():
                for alias in page['Aliases']:
                    if alias.get('TargetKeyId') == key_id:
                        aliases.append(alias['AliasName'])
            
            return aliases
            
        except ClientError:
            return []
    
    def get_key_grants(self, key_id: str, region: str) -> int:
        """Get number of grants for a KMS key"""
        try:
            kms = self.session.client('kms', region_name=region)
            
            grants = kms.list_grants(KeyId=key_id)
            return len(grants.get('Grants', []))
            
        except ClientError:
            return 0
    
    def check_key_safety(self, key_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if KMS key appears to be important or in use"""
        key_id = key_info['key_id']
        safety_warnings = []
        
        # Check for important patterns in description or aliases
        description = key_info.get('description', '').lower()
        aliases = [alias.lower() for alias in key_info.get('aliases', [])]
        
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary',
            'backup', 'database', 'rds', 's3', 'ebs', 'secrets'
        ]
        
        for pattern in important_patterns:
            if pattern in description or any(pattern in alias for alias in aliases):
                safety_warnings.append(f"Contains '{pattern}' - might be important")
                break
        
        # Check if key has recent usage
        if key_info.get('usage_stats', {}).get('has_recent_usage'):
            usage_count = key_info['usage_stats']['total_usage_events']
            safety_warnings.append(f"Recent usage: {usage_count} events in 30 days")
        
        # Check if key has grants (other AWS services using it)
        grant_count = key_info.get('grant_count', 0)
        if grant_count > 0:
            safety_warnings.append(f"Has {grant_count} grants (services using this key)")
        
        # Check if key has aliases (indicates it's being used intentionally)
        if key_info.get('aliases'):
            safety_warnings.append(f"Has aliases: {', '.join(key_info['aliases'][:2])}")
        
        # Check if key is for AWS services (check key policy)
        key_policy = key_info.get('key_policy', {})
        if key_policy and 'Statement' in key_policy:
            for statement in key_policy['Statement']:
                principal = statement.get('Principal', {})
                if isinstance(principal, dict) and 'Service' in principal:
                    services = principal['Service'] if isinstance(principal['Service'], list) else [principal['Service']]
                    aws_services = [s for s in services if s.endswith('.amazonaws.com')]
                    if aws_services:
                        safety_warnings.append(f"Used by AWS services: {', '.join(aws_services[:2])}")
                        break
        
        # Check if key was recently created (within 7 days)
        created_time = key_info['creation_date']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        # Check key origin (AWS_KMS vs EXTERNAL vs AWS_CLOUDHSM)
        if key_info.get('origin') != 'AWS_KMS':
            safety_warnings.append(f"Key origin: {key_info.get('origin')} (not standard AWS KMS)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def list_kms_keys_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all customer-managed KMS keys in a specific region"""
        try:
            kms = self.session.client('kms', region_name=region)
            
            keys = []
            paginator = kms.get_paginator('list_keys')
            
            for page in paginator.paginate():
                for key_summary in page['Keys']:
                    key_id = key_summary['KeyId']
                    
                    try:
                        # Get detailed key information
                        key_details = kms.describe_key(KeyId=key_id)['KeyMetadata']
                        
                        # Skip AWS-managed keys (we only want customer-managed keys)
                        if key_details['KeyManager'] != 'CUSTOMER':
                            continue
                        
                        # Skip keys that are pending deletion
                        if key_details['KeyState'] == 'PendingDeletion':
                            continue
                        
                        # Get key policy
                        key_policy = {}
                        try:
                            policy_response = kms.get_key_policy(KeyId=key_id, PolicyName='default')
                            key_policy = json.loads(policy_response['Policy'])
                        except ClientError:
                            pass
                        
                        # Get aliases
                        aliases = self.get_key_aliases(key_id, region)
                        
                        # Get usage statistics
                        usage_stats = self.get_key_usage_stats(key_id, region)
                        
                        # Get grants
                        grant_count = self.get_key_grants(key_id, region)
                        
                        # Calculate monthly cost ($1 per key per month)
                        monthly_cost = 1.0
                        
                        key_info = {
                            'key_id': key_id,
                            'region': region,
                            'arn': key_details['Arn'],
                            'description': key_details.get('Description', ''),
                            'key_usage': key_details['KeyUsage'],
                            'key_state': key_details['KeyState'],
                            'creation_date': key_details['CreationDate'],
                            'enabled': key_details.get('Enabled', False),
                            'origin': key_details.get('Origin', 'AWS_KMS'),
                            'key_spec': key_details.get('KeySpec', 'SYMMETRIC_DEFAULT'),
                            'encryption_algorithms': key_details.get('EncryptionAlgorithms', []),
                            'aliases': aliases,
                            'grant_count': grant_count,
                            'usage_stats': usage_stats,
                            'key_policy': key_policy,
                            'monthly_cost': monthly_cost
                        }
                        
                        # Add safety check
                        key_info['safety'] = self.check_key_safety(key_info)
                        
                        keys.append(key_info)
                        
                    except ClientError as e:
                        # Skip keys we can't access (might be from other accounts, etc.)
                        if 'AccessDenied' not in str(e):
                            print(f"    {Colors.YELLOW}Warning: Cannot access key {key_id}: {e}{Colors.END}")
                        continue
            
            return keys
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing KMS keys in {region}: {e}{Colors.END}")
            return []
    
    def format_key_info(self, key: Dict[str, Any]) -> str:
        """Format key information for display"""
        key_id = key['key_id'][:20]
        region = key['region']
        description = key['description'][:20] if key['description'] else 'No description'
        key_state = key['key_state'][:10]
        
        # Alias display
        aliases = key['aliases']
        alias_display = aliases[0][:15] if aliases else 'No alias'
        
        # Usage indicator
        usage_stats = key['usage_stats']
        if usage_stats.get('has_recent_usage'):
            usage = f"{usage_stats['total_usage_events']} uses"
        else:
            usage = "No usage"
        
        created_time = key['creation_date']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Enabled status
        enabled = "✓" if key['enabled'] else "✗"
        
        # Grants
        grant_count = key['grant_count']
        
        # Safety indicator
        if key['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {key_id:<20} | {region:<12} | {description:<20} | {alias_display:<15} | {key_state:<10} | {enabled:<3} | {grant_count:>2} | {usage:<10} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_keys(self) -> List[Dict[str, Any]]:
        """List all customer-managed KMS keys across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*150}{Colors.END}")
        print(f"{Colors.BLUE}Scanning KMS Customer-Managed Keys across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*150}{Colors.END}")
        
        all_keys = []
        total_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            keys = self.list_kms_keys_in_region(region)
            
            if keys:
                region_cost = len(keys) * 1.0  # $1 per key per month
                
                enabled_count = sum(1 for key in keys if key['enabled'])
                disabled_count = len(keys) - enabled_count
                
                print(f"{Colors.GREEN}Found {len(keys)} customer-managed keys{Colors.END}")
                print(f"  Enabled: {enabled_count}, Disabled: {disabled_count}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                all_keys.extend(keys)
            else:
                print(f"{Colors.GREEN}No customer-managed keys found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for key in all_keys if key['safety']['is_risky'])
        unused_count = sum(1 for key in all_keys if not key['usage_stats'].get('has_recent_usage', False))
        disabled_count = sum(1 for key in all_keys if not key['enabled'])
        
        print(f"\n{Colors.BOLD}KMS KEYS SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*150}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total customer-managed keys: {Colors.YELLOW}{len(all_keys)}{Colors.END}")
        print(f"Keys with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused keys (no recent activity): {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Disabled keys: {Colors.YELLOW}{disabled_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_keys:
            print(f"\n{Colors.BOLD}KEY DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*150}{Colors.END}")
            print(f"  {'Key ID':<20} | {'Region':<12} | {'Description':<20} | {'Alias':<15} | {'State':<10} | {'En':<3} | {'Gr':<2} | {'Usage':<10} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*12} | {'-'*20} | {'-'*15} | {'-'*10} | {'-'*3} | {'-'*2} | {'-'*10} | {'-'*4} | {'-'*4}")
            
            # Sort by safety risk (risky first), then by age (oldest first)
            sorted_keys = sorted(all_keys, key=lambda x: (not x['safety']['is_risky'], -x['safety']['days_since_created']))
            
            for key in sorted_keys:
                print(self.format_key_info(key))
                
                # Show safety warnings
                if key['safety']['warnings']:
                    for warning in key['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by state
            print(f"\n{Colors.BOLD}BREAKDOWN BY KEY STATE{Colors.END}")
            states = {}
            for key in all_keys:
                state = key['key_state']
                if state not in states:
                    states[state] = {'count': 0, 'cost': 0}
                states[state]['count'] += 1
                states[state]['cost'] += key['monthly_cost']
            
            for state, stats in sorted(states.items()):
                print(f"  {state:<15}: {stats['count']} keys, ${stats['cost']:.2f}/month")
        
        return all_keys
    
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
    
    def show_key_selection_menu(self, keys: List[Dict[str, Any]]) -> List[str]:
        """Show menu for key selection"""
        if not keys:
            return []
        
        print(f"\n{Colors.BOLD}SELECT KEYS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter key numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all keys")
        print("Or enter 'unused' to select keys with no recent usage")
        print("Or enter 'disabled' to select disabled keys")
        print("Or enter 'safe' to select only keys without warnings")
        print("")
        
        # Show numbered list
        unused_keys = []
        safe_keys = []
        disabled_keys = []
        
        for i, key in enumerate(keys, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if key['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            
            # Truncate display for readability
            description = key['description'][:25] if key['description'] else 'No description'
            aliases = key['aliases']
            alias_display = aliases[0][:20] if aliases else 'No alias'
            
            usage_indicator = ""
            if not key['usage_stats'].get('has_recent_usage', False):
                usage_indicator = f"{Colors.YELLOW}(UNUSED){Colors.END}"
                unused_keys.append(key['key_id'])
            
            if not key['enabled']:
                disabled_keys.append(key['key_id'])
            
            if not key['safety']['is_risky']:
                safe_keys.append(key['key_id'])
            
            print(f"{i:2d}. {key['key_id']:<20} | {key['region']:<12} | {description:<25} | {alias_display:<20} | {safety_indicator} {usage_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [key['key_id'] for key in keys]
            elif choice == 'unused':
                if unused_keys:
                    return unused_keys
                else:
                    print(f"{Colors.RED}No unused keys found{Colors.END}")
                    continue
            elif choice == 'disabled':
                if disabled_keys:
                    return disabled_keys
                else:
                    print(f"{Colors.RED}No disabled keys found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_keys:
                    return safe_keys
                else:
                    print(f"{Colors.RED}No 'safe' keys found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(keys):
                            selected.append(keys[idx-1]['key_id'])
                        else:
                            print(f"{Colors.RED}Invalid key number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'unused', 'disabled', or 'safe'{Colors.END}")
    
    def schedule_key_deletion(self, key: Dict[str, Any], pending_window_days: int = 7, dry_run: bool = False) -> bool:
        """Schedule a KMS key for deletion"""
        key_id = key['key_id']
        region = key['region']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would schedule key {key_id} for deletion in {pending_window_days} days{Colors.END}")
            return True
        
        try:
            kms = self.session.client('kms', region_name=region)
            
            # Schedule key for deletion
            kms.schedule_key_deletion(
                KeyId=key_id,
                PendingWindowInDays=pending_window_days
            )
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'KMSInvalidStateException':
                if 'is pending deletion' in str(e):
                    print(f"  {Colors.YELLOW}Key {key_id} is already scheduled for deletion{Colors.END}")
                    return True
                else:
                    print(f"  {Colors.RED}Key {key_id} is in invalid state: {e}{Colors.END}")
            elif error_code == 'NotFoundException':
                print(f"  {Colors.YELLOW}Key {key_id} not found (already deleted?){Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error scheduling {key_id} for deletion: {e}{Colors.END}")
            return False
    
    def delete_keys(self, keys: List[Dict[str, Any]], selected_key_ids: List[str], pending_window_days: int = 7, dry_run: bool = False):
        """Schedule selected keys for deletion"""
        keys_to_delete = [key for key in keys if key['key_id'] in selected_key_ids]
        
        if not keys_to_delete:
            print(f"{Colors.YELLOW}No keys selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}{mode_text}SCHEDULING KMS KEYS FOR DELETION{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}Keys will be deleted after {pending_window_days} days pending period!{Colors.END}")
            print(f"{Colors.RED}This action can be cancelled during the pending period!{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        
        scheduled_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, key in enumerate(keys_to_delete, 1):
            key_id = key['key_id']
            region = key['region']
            description = key['description'] or 'No description'
            monthly_cost = key['monthly_cost']
            
            print(f"\n[{i}/{len(keys_to_delete)}] Processing key: {key_id}")
            print(f"  Description: {description}")
            print(f"  Region: {region}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if key['safety']['warnings']:
                for warning in key['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.schedule_key_deletion(key, pending_window_days, dry_run):
                action_text = "Would schedule" if dry_run else "Successfully scheduled"
                print(f"  {Colors.GREEN}✓ {action_text} {key_id} for deletion{Colors.END}")
                scheduled_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to schedule {key_id} for deletion{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            if not dry_run:
                time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        action_text = "would be scheduled" if dry_run else "scheduled"
        print(f"Successfully {action_text}: {Colors.GREEN}{scheduled_count} keys{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} keys{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and scheduled_count > 0:
            print(f"\n{Colors.YELLOW}Important Notes:{Colors.END}")
            print(f"• Keys are scheduled for deletion in {pending_window_days} days")
            print(f"• You can cancel deletion during the pending period")
            print(f"• Use 'aws kms cancel-key-deletion --key-id <key-id>' to cancel")
            print(f"• After deletion, encrypted data using these keys will be permanently inaccessible")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS KMS Keys Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all keys
        keys = self.list_all_keys()
        
        if not keys:
            print(f"\n{Colors.GREEN}No customer-managed KMS keys found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(key['monthly_cost'] for key in keys)
        risky_count = sum(1 for key in keys if key['safety']['is_risky'])
        unused_count = sum(1 for key in keys if not key['usage_stats'].get('has_recent_usage', False))
        disabled_count = sum(1 for key in keys if not key['enabled'])
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total customer-managed keys: {Colors.BLUE}{len(keys)}{Colors.END}")
        print(f"Keys with safety warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Unused keys (no recent activity): {Colors.YELLOW}{unused_count}{Colors.END}")
        print(f"Disabled keys: {Colors.YELLOW}{disabled_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  Key deletion has a pending period (7-30 days)!{Colors.END}")
            print(f"{Colors.RED}⚠️  Encrypted data will become permanently inaccessible!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with key selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select keys
        selected_key_ids = self.show_key_selection_menu(keys)
        
        if not selected_key_ids:
            print(f"{Colors.BLUE}No keys selected. Exiting.{Colors.END}")
            return
        
        selected_keys = [key for key in keys if key['key_id'] in selected_key_ids]
        selected_cost = sum(key['monthly_cost'] for key in selected_keys)
        
        # Ask about pending window
        pending_window_days = 7
        if not dry_run:
            print(f"\n{Colors.YELLOW}DELETION PENDING WINDOW{Colors.END}")
            print("KMS keys have a mandatory pending period before deletion (7-30 days).")
            print("During this time, you can cancel the deletion if needed.")
            
            while True:
                try:
                    days_input = input(f"Enter pending window days (7-30, default 7): ").strip()
                    if not days_input:
                        pending_window_days = 7
                        break
                    
                    pending_window_days = int(days_input)
                    if 7 <= pending_window_days <= 30:
                        break
                    else:
                        print(f"{Colors.RED}Please enter a number between 7 and 30{Colors.END}")
                except ValueError:
                    print(f"{Colors.RED}Please enter a valid number{Colors.END}")
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected keys: {Colors.YELLOW}{len(selected_keys)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"Pending window: {Colors.YELLOW}{pending_window_days} days{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else f"Are you sure you want to schedule these keys for deletion?"
        if self.get_user_confirmation(final_question):
            self.delete_keys(keys, selected_key_ids, pending_window_days, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS KMS Keys Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 kms_cleanup.py                          # Use default AWS profile
  python3 kms_cleanup.py --profile dev            # Use specific profile
  python3 kms_cleanup.py --dry-run                # Test mode - no actual deletions
  
Features:
  - Lists all customer-managed KMS keys with usage analysis
  - Shows activity metrics and grant information
  - Identifies unused keys with no recent cryptographic operations
  - Safety warnings for keys used by AWS services
  - Cost impact: $1/month per key (can add up with many keys)
  - Schedules keys for deletion with configurable pending period
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
        cleaner = KMSCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()