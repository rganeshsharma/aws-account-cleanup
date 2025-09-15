#!/usr/bin/env python3
"""
AWS S3 Bucket Cleanup Tool
Lists all S3 buckets with detailed information and allows safe deletion.
Handles object deletion, versioning, and provides cost estimates.
"""

import boto3
import argparse
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from botocore.exceptions import ClientError, NoCredentialsError
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    BOLD = '\033[1m'
    END = '\033[0m'

class S3BucketCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS S3 bucket cleaner"""
        self.profile_name = profile_name
        self.session = None
        self.s3_client = None
        self.s3_resource = None
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
            
            # Initialize S3 client and resource
            self.s3_client = self.session.client('s3')
            self.s3_resource = self.session.resource('s3')
            
        except NoCredentialsError:
            print(f"{Colors.RED}Error: AWS credentials not found!{Colors.END}")
            print("Please run: aws configure")
            sys.exit(1)
        except ClientError as e:
            print(f"{Colors.RED}Error: {e}{Colors.END}")
            sys.exit(1)
    
    def get_bucket_location(self, bucket_name: str) -> str:
        """Get the region where bucket is located"""
        try:
            response = self.s3_client.get_bucket_location(Bucket=bucket_name)
            location = response.get('LocationConstraint')
            # AWS returns None for us-east-1
            return location if location else 'us-east-1'
        except ClientError as e:
            print(f"{Colors.YELLOW}Warning: Cannot get location for {bucket_name}: {e}{Colors.END}")
            return 'unknown'
    
    def get_bucket_size_and_objects(self, bucket_name: str) -> Dict[str, Any]:
        """Get bucket size and object count using CloudWatch metrics"""
        try:
            bucket_region = self.get_bucket_location(bucket_name)
            if bucket_region == 'unknown':
                return {'size_bytes': 0, 'object_count': 0, 'estimated_cost': 0}
            
            cloudwatch = self.session.client('cloudwatch', region_name=bucket_region)
            
            # Get storage size (Standard storage class)
            size_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/S3',
                MetricName='BucketSizeBytes',
                Dimensions=[
                    {'Name': 'BucketName', 'Value': bucket_name},
                    {'Name': 'StorageType', 'Value': 'StandardStorage'}
                ],
                StartTime=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
                EndTime=datetime.now(timezone.utc),
                Period=86400,  # 24 hours
                Statistics=['Average']
            )
            
            # Get object count
            count_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/S3',
                MetricName='NumberOfObjects',
                Dimensions=[
                    {'Name': 'BucketName', 'Value': bucket_name},
                    {'Name': 'StorageType', 'Value': 'AllStorageTypes'}
                ],
                StartTime=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
                EndTime=datetime.now(timezone.utc),
                Period=86400,  # 24 hours
                Statistics=['Average']
            )
            
            size_bytes = 0
            if size_response['Datapoints']:
                size_bytes = max(dp['Average'] for dp in size_response['Datapoints'])
            
            object_count = 0
            if count_response['Datapoints']:
                object_count = int(max(dp['Average'] for dp in count_response['Datapoints']))
            
            # Estimate monthly cost (rough calculation)
            size_gb = size_bytes / (1024**3)
            estimated_cost = size_gb * 0.023  # $0.023 per GB-month for Standard storage
            
            return {
                'size_bytes': int(size_bytes),
                'object_count': object_count,
                'estimated_cost': estimated_cost
            }
            
        except ClientError as e:
            # If CloudWatch metrics not available, try to count manually (slower)
            return self.count_objects_manually(bucket_name)
    
    def count_objects_manually(self, bucket_name: str, max_objects: int = 1000) -> Dict[str, Any]:
        """Manually count objects in bucket (limited for performance)"""
        try:
            bucket = self.s3_resource.Bucket(bucket_name)
            total_size = 0
            object_count = 0
            
            # Only count first max_objects for performance
            for obj in bucket.objects.limit(max_objects):
                total_size += obj.size
                object_count += 1
            
            # If we hit the limit, indicate there are more
            is_approximate = object_count >= max_objects
            
            size_gb = total_size / (1024**3)
            estimated_cost = size_gb * 0.023
            
            return {
                'size_bytes': total_size,
                'object_count': object_count,
                'estimated_cost': estimated_cost,
                'is_approximate': is_approximate
            }
            
        except ClientError as e:
            print(f"{Colors.YELLOW}Warning: Cannot access bucket {bucket_name}: {e}{Colors.END}")
            return {'size_bytes': 0, 'object_count': 0, 'estimated_cost': 0, 'error': str(e)}
    
    def format_size(self, size_bytes: int) -> str:
        """Format bytes into human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        size = float(size_bytes)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        return f"{size:.1f} {units[unit_index]}"
    
    def check_bucket_safety(self, bucket_name: str) -> Dict[str, Any]:
        """Check if bucket looks important/dangerous to delete"""
        safety_warnings = []
        
        # Check for common important bucket patterns
        important_patterns = [
            'backup', 'prod', 'production', 'website', 'cdn', 'assets',
            'terraform', 'cloudformation', 'logs', 'archive'
        ]
        
        bucket_lower = bucket_name.lower()
        for pattern in important_patterns:
            if pattern in bucket_lower:
                safety_warnings.append(f"Contains '{pattern}' - might be important")
        
        # Check for versioning
        try:
            versioning = self.s3_client.get_bucket_versioning(Bucket=bucket_name)
            if versioning.get('Status') == 'Enabled':
                safety_warnings.append("Versioning enabled - will delete all versions")
        except ClientError:
            pass
        
        # Check for lifecycle policies
        try:
            self.s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            safety_warnings.append("Has lifecycle policies")
        except ClientError:
            pass
        
        # Check for public access
        try:
            public_access = self.s3_client.get_public_access_block(Bucket=bucket_name)
            if not all(public_access.get('PublicAccessBlockConfiguration', {}).values()):
                safety_warnings.append("May have public access")
        except ClientError:
            pass
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings
        }
    
    def format_bucket_info(self, bucket: Dict[str, Any]) -> str:
        """Format bucket information for display"""
        name = bucket['name']
        region = bucket['region']
        creation_date = bucket['creation_date'].strftime('%Y-%m-%d %H:%M')
        size = self.format_size(bucket['size_bytes'])
        object_count = bucket['object_count']
        monthly_cost = bucket['estimated_cost']
        
        # Safety indicators
        if bucket['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        # Approximate indicator
        approx = " (~)" if bucket.get('is_approximate', False) else ""
        
        return f"  {name:<30} | {region:<12} | {size:>10} | {object_count:>8}{approx} | ${monthly_cost:>6.2f} | {creation_date} | {safety_indicator}"
    
    def list_all_buckets(self) -> List[Dict[str, Any]]:
        """List all S3 buckets with detailed information"""
        print(f"\n{Colors.BLUE}{'='*100}{Colors.END}")
        print(f"{Colors.BLUE}Scanning S3 Buckets (this may take a moment for size calculation)...{Colors.END}")
        print(f"{Colors.BLUE}{'='*100}{Colors.END}")
        
        try:
            response = self.s3_client.list_buckets()
            buckets = response['Buckets']
        except ClientError as e:
            print(f"{Colors.RED}Error listing buckets: {e}{Colors.END}")
            return []
        
        if not buckets:
            print(f"{Colors.GREEN}No S3 buckets found.{Colors.END}")
            return []
        
        print(f"Found {len(buckets)} buckets. Analyzing...")
        
        detailed_buckets = []
        
        # Use threading for faster processing
        def analyze_bucket(bucket):
            bucket_name = bucket['Name']
            print(f"{Colors.YELLOW}Analyzing {bucket_name}...{Colors.END}")
            
            region = self.get_bucket_location(bucket_name)
            size_info = self.get_bucket_size_and_objects(bucket_name)
            safety_info = self.check_bucket_safety(bucket_name)
            
            return {
                'name': bucket_name,
                'creation_date': bucket['CreationDate'],
                'region': region,
                'size_bytes': size_info['size_bytes'],
                'object_count': size_info['object_count'],
                'estimated_cost': size_info['estimated_cost'],
                'is_approximate': size_info.get('is_approximate', False),
                'error': size_info.get('error'),
                'safety': safety_info
            }
        
        # Process buckets in parallel for speed
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_bucket = {executor.submit(analyze_bucket, bucket): bucket for bucket in buckets}
            
            for future in as_completed(future_to_bucket):
                try:
                    bucket_info = future.result()
                    detailed_buckets.append(bucket_info)
                except Exception as e:
                    bucket = future_to_bucket[future]
                    print(f"{Colors.RED}Error analyzing {bucket['Name']}: {e}{Colors.END}")
        
        # Calculate totals
        total_size = sum(b['size_bytes'] for b in detailed_buckets)
        total_objects = sum(b['object_count'] for b in detailed_buckets)
        total_cost = sum(b['estimated_cost'] for b in detailed_buckets)
        risky_buckets = sum(1 for b in detailed_buckets if b['safety']['is_risky'])
        
        # Display summary
        print(f"\n{Colors.BOLD}S3 BUCKET SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*100}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total buckets found: {Colors.YELLOW}{len(detailed_buckets)}{Colors.END}")
        print(f"Total storage size: {Colors.YELLOW}{self.format_size(total_size)}{Colors.END}")
        print(f"Total objects: {Colors.YELLOW}{total_objects:,}{Colors.END}")
        print(f"Estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Buckets with safety warnings: {Colors.RED}{risky_buckets}{Colors.END}")
        print(f"Scope: {Colors.YELLOW}All buckets in account{Colors.END}")
        
        if detailed_buckets:
            print(f"\n{Colors.BOLD}BUCKET DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*100}{Colors.END}")
            print(f"  {'Bucket Name':<30} | {'Region':<12} | {'Size':<10} | {'Objects':<8} | {'Cost':<7} | {'Created':<16} | Safe")
            print(f"  {'-'*30} | {'-'*12} | {'-'*10} | {'-'*8} | {'-'*7} | {'-'*16} | {'-'*4}")
            
            # Sort by cost (highest first), then by size
            sorted_buckets = sorted(detailed_buckets, key=lambda x: (-x['estimated_cost'], -x['size_bytes']))
            
            for bucket in sorted_buckets:
                print(self.format_bucket_info(bucket))
                
                # Show safety warnings
                if bucket['safety']['warnings']:
                    for warning in bucket['safety']['warnings'][:2]:  # Show first 2 warnings
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show regional breakdown
            print(f"\n{Colors.BOLD}BREAKDOWN BY REGION{Colors.END}")
            regions = {}
            for bucket in detailed_buckets:
                region = bucket['region']
                if region not in regions:
                    regions[region] = {'count': 0, 'size': 0, 'cost': 0}
                regions[region]['count'] += 1
                regions[region]['size'] += bucket['size_bytes']
                regions[region]['cost'] += bucket['estimated_cost']
            
            for region, stats in sorted(regions.items()):
                print(f"  {region:<15}: {stats['count']} buckets, {self.format_size(stats['size'])}, ${stats['cost']:.2f}/month")
        
        return detailed_buckets
    
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
    
    def empty_bucket(self, bucket_name: str) -> bool:
        """Empty all objects and versions from a bucket"""
        try:
            bucket = self.s3_resource.Bucket(bucket_name)
            
            print(f"  Deleting all objects in {bucket_name}...")
            
            # Delete all object versions first
            bucket.object_versions.delete()
            
            # Delete any remaining objects
            bucket.objects.all().delete()
            
            print(f"  {Colors.GREEN}✓ Emptied bucket {bucket_name}{Colors.END}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                print(f"  {Colors.YELLOW}Bucket {bucket_name} already deleted{Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error emptying {bucket_name}: {e}{Colors.END}")
                return False
    
    def delete_bucket(self, bucket_name: str) -> bool:
        """Delete an empty S3 bucket"""
        try:
            self.s3_client.delete_bucket(Bucket=bucket_name)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                print(f"  {Colors.YELLOW}Bucket {bucket_name} already deleted{Colors.END}")
                return True
            elif error_code == 'BucketNotEmpty':
                print(f"  {Colors.RED}Error: Bucket {bucket_name} is not empty{Colors.END}")
                return False
            else:
                print(f"  {Colors.RED}Error deleting {bucket_name}: {e}{Colors.END}")
                return False
    
    def delete_buckets(self, buckets: List[Dict[str, Any]], selected_buckets: List[str] = None):
        """Delete selected buckets with their contents"""
        if selected_buckets is None:
            buckets_to_delete = buckets
        else:
            buckets_to_delete = [b for b in buckets if b['name'] in selected_buckets]
        
        if not buckets_to_delete:
            print(f"{Colors.YELLOW}No buckets selected for deletion.{Colors.END}")
            return
        
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}DELETING S3 BUCKETS AND ALL CONTENTS - THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*70}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, bucket in enumerate(buckets_to_delete, 1):
            bucket_name = bucket['name']
            monthly_cost = bucket['estimated_cost']
            object_count = bucket['object_count']
            size = self.format_size(bucket['size_bytes'])
            
            print(f"\n[{i}/{len(buckets_to_delete)}] Deleting bucket: {bucket_name}")
            print(f"  Size: {size}, Objects: {object_count:,}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings if any
            if bucket['safety']['warnings']:
                for warning in bucket['safety']['warnings']:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # First empty the bucket
            if object_count > 0:
                if self.empty_bucket(bucket_name):
                    time.sleep(1)  # Wait a moment after emptying
                else:
                    print(f"  {Colors.RED}✗ Failed to empty {bucket_name}{Colors.END}")
                    failed_count += 1
                    continue
            
            # Then delete the bucket
            if self.delete_bucket(bucket_name):
                print(f"  {Colors.GREEN}✓ Successfully deleted {bucket_name}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {bucket_name}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        print(f"Successfully deleted: {Colors.GREEN}{deleted_count} buckets{Colors.END}")
        print(f"Failed to delete: {Colors.RED}{failed_count} buckets{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if deleted_count > 0 and failed_count == 0:
            print(f"\n{Colors.GREEN}All selected buckets deleted successfully!{Colors.END}")
    
    def show_bucket_selection_menu(self, buckets: List[Dict[str, Any]]) -> List[str]:
        """Show menu for bucket selection"""
        if not buckets:
            return []
        
        print(f"\n{Colors.BOLD}SELECT BUCKETS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        print("Enter bucket numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all buckets")
        print("Or enter 'safe' to select only buckets without warnings")
        print("")
        
        # Show numbered list
        safe_buckets = []
        for i, bucket in enumerate(buckets, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if bucket['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            size = self.format_size(bucket['size_bytes'])
            cost = bucket['estimated_cost']
            
            print(f"{i:2d}. {bucket['name']:<30} | {size:>10} | ${cost:>6.2f}/mo | {safety_indicator}")
            
            if not bucket['safety']['is_risky']:
                safe_buckets.append(bucket['name'])
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [b['name'] for b in buckets]
            elif choice == 'safe':
                if safe_buckets:
                    return safe_buckets
                else:
                    print(f"{Colors.RED}No 'safe' buckets found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    # Parse comma-separated numbers
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(buckets):
                            selected.append(buckets[idx-1]['name'])
                        else:
                            print(f"{Colors.RED}Invalid bucket number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', or 'safe'{Colors.END}")
    
    def run(self):
        """Main execution flow"""
        print(f"{Colors.BOLD}AWS S3 Bucket Cleanup Tool{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        
        # List all buckets
        buckets = self.list_all_buckets()
        
        if not buckets:
            print(f"\n{Colors.GREEN}No S3 buckets found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(b['estimated_cost'] for b in buckets)
        risky_count = sum(1 for b in buckets if b['safety']['is_risky'])
        safe_count = len(buckets) - risky_count
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total buckets: {Colors.BLUE}{len(buckets)}{Colors.END}")
        print(f"Buckets with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Buckets without warnings: {Colors.GREEN}{safe_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"{Colors.RED}⚠️  Deletion will remove ALL objects and versions in selected buckets!{Colors.END}")
        print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask what user wants to do
        if not self.get_user_confirmation("Do you want to proceed with bucket selection?"):
            print(f"{Colors.BLUE}No buckets were deleted.{Colors.END}")
            return
        
        # Let user select buckets
        selected_bucket_names = self.show_bucket_selection_menu(buckets)
        
        if not selected_bucket_names:
            print(f"{Colors.BLUE}No buckets selected. Exiting.{Colors.END}")
            return
        
        selected_buckets = [b for b in buckets if b['name'] in selected_bucket_names]
        selected_cost = sum(b['estimated_cost'] for b in selected_buckets)
        selected_size = sum(b['size_bytes'] for b in selected_buckets)
        
        # Final confirmation
        print(f"\n{Colors.RED}FINAL CONFIRMATION{Colors.END}")
        print(f"Selected buckets: {Colors.YELLOW}{len(selected_buckets)}{Colors.END}")
        print(f"Total size to delete: {Colors.YELLOW}{self.format_size(selected_size)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        
        if self.get_user_confirmation("Are you absolutely sure you want to delete these buckets?"):
            self.delete_buckets(buckets, selected_bucket_names)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS S3 Bucket Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 s3_cleanup.py                    # Use default AWS profile
  python3 s3_cleanup.py --profile dev      # Use specific profile
  
Features:
  - Lists all S3 buckets with size and cost estimates
  - Shows safety warnings for potentially important buckets
  - Allows selective deletion of buckets
  - Handles object versioning and lifecycle policies
  - Provides detailed cost analysis
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help='AWS profile to use (default: uses default profile)'
    )
    
    args = parser.parse_args()
    
    try:
        cleaner = S3BucketCleaner(profile_name=args.profile)
        cleaner.run()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()