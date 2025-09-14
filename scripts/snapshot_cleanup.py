#!/usr/bin/env python3
"""
AWS EBS Snapshot Cleanup Tool
Lists all EBS snapshots and asks for confirmation before deletion.
"""

import boto3
import argparse
import sys
from datetime import datetime
from typing import List, Dict, Any
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
import time

class Colors:
    """ANSI color codes for terminal output"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    BOLD = '\033[1m'
    END = '\033[0m'

class AWSSnapshotCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS snapshot cleaner"""
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
            'eu-central-1'      #Frankfurt
            # 'us-east-1',      # N. Virginia
            # 'us-west-2',      # Oregon  
            # 'ap-south-1',     # Mumbai (closest to Bengaluru)
            # 'ap-southeast-1', # Singapore
            # 'eu-west-1',      # Ireland
        ]
        
        accessible_regions = []
        print(f"\n{Colors.BLUE}Testing region connectivity...{Colors.END}")
        
        for region in test_regions:
            try:
                ec2 = self.session.client('ec2', region_name=region)
                # Quick test with short timeout
                ec2.describe_regions()
                print(f"{Colors.GREEN}✓ {region} - accessible{Colors.END}")
                accessible_regions.append(region)
            except (EndpointConnectionError, ClientError) as e:
                print(f"{Colors.RED}✗ {region} - not accessible ({str(e)[:50]}...){Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}✗ {region} - error: {str(e)[:50]}...{Colors.END}")
        
        if not accessible_regions:
            print(f"{Colors.RED}Error: No accessible regions found!{Colors.END}")
            sys.exit(1)
            
        self.accessible_regions = accessible_regions
        return accessible_regions
    
    def list_snapshots_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all EBS snapshots owned by the current account in a specific region"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            
            # Get snapshots owned by current account
            response = ec2.describe_snapshots(OwnerIds=['self'])
            snapshots = response['Snapshots']
            
            # Add region info to each snapshot
            for snapshot in snapshots:
                snapshot['Region'] = region
                
            return snapshots
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing snapshots in {region}: {e}{Colors.END}")
            return []
    
    def format_snapshot_info(self, snapshot: Dict[str, Any]) -> str:
        """Format snapshot information for display"""
        snap_id = snapshot['SnapshotId']
        description = snapshot.get('Description', 'No description')[:50]
        start_time = snapshot['StartTime'].strftime('%Y-%m-%d %H:%M:%S')
        size_gb = snapshot['VolumeSize']
        state = snapshot['State']
        progress = snapshot.get('Progress', 'N/A')
        region = snapshot['Region']
        
        return f"  {snap_id} | {region:12} | {size_gb:3}GB | {state:10} | {progress:8} | {start_time} | {description}"
    
    def list_all_snapshots(self) -> List[Dict[str, Any]]:
        """List all snapshots across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*80}{Colors.END}")
        print(f"{Colors.BLUE}Scanning for EBS Snapshots across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*80}{Colors.END}")
        
        all_snapshots = []
        total_size_gb = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            snapshots = self.list_snapshots_in_region(region)
            
            if snapshots:
                print(f"{Colors.GREEN}Found {len(snapshots)} snapshots{Colors.END}")
                region_size = sum(snap['VolumeSize'] for snap in snapshots)
                print(f"{Colors.GREEN}Total size: {region_size} GB{Colors.END}")
                total_size_gb += region_size
                all_snapshots.extend(snapshots)
            else:
                print(f"{Colors.GREEN}No snapshots found{Colors.END}")
        
        # Display summary
        print(f"\n{Colors.BOLD}SNAPSHOT SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*80}{Colors.END}")
        print(f"Total snapshots found: {Colors.YELLOW}{len(all_snapshots)}{Colors.END}")
        print(f"Total storage size: {Colors.YELLOW}{total_size_gb} GB{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_snapshots:
            print(f"\n{Colors.BOLD}SNAPSHOT DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*80}{Colors.END}")
            print(f"  {'Snapshot ID':<21} | {'Region':<12} | {'Size':<5} | {'State':<10} | {'Progress':<8} | {'Created':<19} | Description")
            print(f"  {'-'*21} | {'-'*12} | {'-'*5} | {'-'*10} | {'-'*8} | {'-'*19} | {'-'*20}")
            
            # Sort by region, then by creation time
            sorted_snapshots = sorted(all_snapshots, key=lambda x: (x['Region'], x['StartTime']))
            
            for snapshot in sorted_snapshots:
                print(self.format_snapshot_info(snapshot))
        
        return all_snapshots
    
    def get_user_confirmation(self, message: str) -> bool:
        """Get user confirmation for deletion"""
        while True:
            response = input(f"\n{Colors.YELLOW}{message} (y/n): {Colors.END}").lower().strip()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print(f"{Colors.RED}Please enter 'y' for yes or 'n' for no{Colors.END}")
    
    def delete_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """Delete a single snapshot"""
        try:
            ec2 = self.session.client('ec2', region_name=snapshot['Region'])
            ec2.delete_snapshot(SnapshotId=snapshot['SnapshotId'])
            return True
        except ClientError as e:
            print(f"{Colors.RED}Error deleting {snapshot['SnapshotId']}: {e}{Colors.END}")
            return False
    
    def delete_all_snapshots(self, snapshots: List[Dict[str, Any]]):
        """Delete all snapshots with progress tracking"""
        print(f"\n{Colors.RED}{'='*60}{Colors.END}")
        print(f"{Colors.RED}DELETING SNAPSHOTS - THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*60}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        
        for i, snapshot in enumerate(snapshots, 1):
            snap_id = snapshot['SnapshotId']
            region = snapshot['Region']
            
            print(f"\n[{i}/{len(snapshots)}] Deleting {snap_id} in {region}...")
            
            if self.delete_snapshot(snapshot):
                print(f"{Colors.GREEN}✓ Successfully deleted {snap_id}{Colors.END}")
                deleted_count += 1
            else:
                print(f"{Colors.RED}✗ Failed to delete {snap_id}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*40}{Colors.END}")
        print(f"Successfully deleted: {Colors.GREEN}{deleted_count}{Colors.END}")
        if failed_count > 0:
            print(f"Failed to delete: {Colors.RED}{failed_count}{Colors.END}")
        else:
            print(f"{Colors.GREEN}All snapshots deleted successfully!{Colors.END}")
    
    def run(self):
        """Main execution flow"""
        print(f"{Colors.BOLD}AWS EBS Snapshot Cleanup Tool{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all snapshots
        snapshots = self.list_all_snapshots()
        
        if not snapshots:
            print(f"\n{Colors.GREEN}No snapshots found! Nothing to delete.{Colors.END}")
            return
        
        # Ask for confirmation
        total_size = sum(snap['VolumeSize'] for snap in snapshots)
        
        print(f"\n{Colors.YELLOW}⚠️  WARNING: You are about to delete {len(snapshots)} snapshots ({total_size} GB total){Colors.END}")
        print(f"{Colors.YELLOW}⚠️  This action CANNOT be undone!{Colors.END}")
        
        if self.get_user_confirmation("Do you want to proceed with deletion?"):
            # Double confirmation for safety
            if self.get_user_confirmation("Are you absolutely sure? This will permanently delete all snapshots!"):
                self.delete_all_snapshots(snapshots)
            else:
                print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")
        else:
            print(f"{Colors.BLUE}No snapshots were deleted.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS EBS Snapshot Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 snapshot_cleanup.py                    # Use default AWS profile
  python3 snapshot_cleanup.py --profile dev      # Use specific profile
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help='AWS profile to use (default: uses default profile)'
    )
    
    args = parser.parse_args()
    
    try:
        cleaner = AWSSnapshotCleaner(profile_name=args.profile)
        cleaner.run()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()