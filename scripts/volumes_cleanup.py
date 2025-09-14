#!/usr/bin/env python3
"""
AWS EBS Volume Cleanup Tool
Lists all EBS volumes and asks for confirmation before deletion.
Only deletes available (unattached) volumes for safety.
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

class AWSVolumeCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS volume cleaner"""
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
    
    def list_volumes_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all EBS volumes in a specific region"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            
            # Get all EBS volumes
            response = ec2.describe_volumes()
            volumes = response['Volumes']
            
            # Add region info and calculated fields to each volume
            for volume in volumes:
                volume['Region'] = region
                
                # Add attachment status
                volume['IsAttached'] = bool(volume.get('Attachments'))
                
                # Add name tag
                tags = volume.get('Tags', [])
                name_tag = next((tag['Value'] for tag in tags if tag['Key'] == 'Name'), '')
                volume['NameTag'] = name_tag
                
                # Calculate monthly cost estimate (rough)
                size_gb = volume['Size']
                vol_type = volume['VolumeType']
                if vol_type == 'gp2':
                    monthly_cost = size_gb * 0.10  # $0.10 per GB-month
                elif vol_type == 'gp3':
                    monthly_cost = size_gb * 0.08  # $0.08 per GB-month
                elif vol_type == 'io1' or vol_type == 'io2':
                    monthly_cost = size_gb * 0.125  # $0.125 per GB-month
                elif vol_type == 'st1':
                    monthly_cost = size_gb * 0.045  # $0.045 per GB-month
                elif vol_type == 'sc1':
                    monthly_cost = size_gb * 0.025  # $0.025 per GB-month
                else:
                    monthly_cost = size_gb * 0.10  # Default estimate
                    
                volume['EstimatedMonthlyCost'] = monthly_cost
                
            return volumes
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing volumes in {region}: {e}{Colors.END}")
            return []
    
    def format_volume_info(self, volume: Dict[str, Any]) -> str:
        """Format volume information for display"""
        vol_id = volume['VolumeId']
        size_gb = volume['Size']
        vol_type = volume['VolumeType']
        state = volume['State']
        region = volume['Region']
        monthly_cost = volume['EstimatedMonthlyCost']
        
        # Check if attached to an instance
        if volume['IsAttached']:
            attachment = volume['Attachments'][0]
            instance_id = attachment['InstanceId']
            device = attachment['Device']
            attachment_info = f"{instance_id}:{device}"
            status_color = Colors.YELLOW
            status = "ATTACHED"
        else:
            attachment_info = "Not attached"
            status_color = Colors.GREEN
            status = "AVAILABLE"
        
        # Get creation time
        create_time = volume['CreateTime'].strftime('%Y-%m-%d %H:%M')
        
        # Get name tag
        name_tag = volume['NameTag'][:15] if volume['NameTag'] else 'No name'
        
        return f"  {vol_id} | {region:12} | {size_gb:3}GB | {vol_type:8} | {status_color}{status:10}{Colors.END} | {attachment_info:22} | ${monthly_cost:5.2f} | {create_time} | {name_tag}"
    
    def list_all_volumes(self) -> List[Dict[str, Any]]:
        """List all EBS volumes across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*100}{Colors.END}")
        print(f"{Colors.BLUE}Scanning for EBS Volumes across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*100}{Colors.END}")
        
        all_volumes = []
        total_size_gb = 0
        attached_count = 0
        total_monthly_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            volumes = self.list_volumes_in_region(region)
            
            if volumes:
                print(f"{Colors.GREEN}Found {len(volumes)} volumes{Colors.END}")
                region_size = sum(vol['Size'] for vol in volumes)
                region_attached = sum(1 for vol in volumes if vol['IsAttached'])
                region_cost = sum(vol['EstimatedMonthlyCost'] for vol in volumes)
                
                print(f"{Colors.GREEN}Total size: {region_size} GB{Colors.END}")
                print(f"{Colors.YELLOW}Attached volumes: {region_attached}{Colors.END}")
                print(f"{Colors.BLUE}Estimated monthly cost: ${region_cost:.2f}{Colors.END}")
                
                total_size_gb += region_size
                attached_count += region_attached
                total_monthly_cost += region_cost
                all_volumes.extend(volumes)
            else:
                print(f"{Colors.GREEN}No volumes found{Colors.END}")
        
        available_count = len(all_volumes) - attached_count
        available_cost = sum(vol['EstimatedMonthlyCost'] for vol in all_volumes if not vol['IsAttached'])
        
        # Display summary
        print(f"\n{Colors.BOLD}EBS VOLUME SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*100}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total volumes found: {Colors.YELLOW}{len(all_volumes)}{Colors.END}")
        print(f"Total storage size: {Colors.YELLOW}{total_size_gb} GB{Colors.END}")
        print(f"Attached volumes: {Colors.YELLOW}{attached_count}{Colors.END}")
        print(f"Available (unattached) volumes: {Colors.GREEN}{available_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_monthly_cost:.2f}{Colors.END}")
        print(f"Potential monthly savings from deleting available volumes: {Colors.GREEN}${available_cost:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        print(f"Scope: {Colors.YELLOW}Account-owned resources only{Colors.END}")
        
        if all_volumes:
            print(f"\n{Colors.BOLD}VOLUME DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*100}{Colors.END}")
            print(f"  {'Volume ID':<21} | {'Region':<12} | {'Size':<5} | {'Type':<8} | {'Status':<10} | {'Attachment':<22} | {'Cost':<6} | {'Created':<16} | Name")
            print(f"  {'-'*21} | {'-'*12} | {'-'*5} | {'-'*8} | {'-'*10} | {'-'*22} | {'-'*6} | {'-'*16} | {'-'*15}")
            
            # Sort by attachment status (available first), then by region, then by cost (highest first)
            sorted_volumes = sorted(all_volumes, key=lambda x: (
                x['IsAttached'],  # Available volumes first
                x['Region'], 
                -x['EstimatedMonthlyCost']  # Highest cost first
            ))
            
            for volume in sorted_volumes:
                print(self.format_volume_info(volume))
                
            # Show breakdown by volume type
            print(f"\n{Colors.BOLD}BREAKDOWN BY VOLUME TYPE{Colors.END}")
            volume_types = {}
            for vol in all_volumes:
                vol_type = vol['VolumeType']
                if vol_type not in volume_types:
                    volume_types[vol_type] = {'count': 0, 'size': 0, 'cost': 0, 'available': 0}
                volume_types[vol_type]['count'] += 1
                volume_types[vol_type]['size'] += vol['Size']
                volume_types[vol_type]['cost'] += vol['EstimatedMonthlyCost']
                if not vol['IsAttached']:
                    volume_types[vol_type]['available'] += 1
            
            for vol_type, stats in volume_types.items():
                print(f"  {vol_type:<8}: {stats['count']} volumes, {stats['size']} GB, ${stats['cost']:.2f}/month ({stats['available']} available)")
        
        return all_volumes
    
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
    
    def delete_volume(self, volume: Dict[str, Any]) -> bool:
        """Delete a single EBS volume"""
        try:
            # Double-check if volume is attached (safety check)
            if volume['IsAttached']:
                attachment = volume['Attachments'][0]
                print(f"{Colors.RED}Cannot delete {volume['VolumeId']}: attached to {attachment['InstanceId']}{Colors.END}")
                print(f"{Colors.YELLOW}Please detach the volume first or stop/terminate the instance{Colors.END}")
                return False
            
            ec2 = self.session.client('ec2', region_name=volume['Region'])
            ec2.delete_volume(VolumeId=volume['VolumeId'])
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'VolumeInUse':
                print(f"{Colors.RED}Error: Volume {volume['VolumeId']} is still in use{Colors.END}")
            elif error_code == 'InvalidVolume.NotFound':
                print(f"{Colors.YELLOW}Volume {volume['VolumeId']} already deleted{Colors.END}")
                return True  # Consider this a success
            else:
                print(f"{Colors.RED}Error deleting {volume['VolumeId']}: {e}{Colors.END}")
            return False
    
    def delete_available_volumes(self, volumes: List[Dict[str, Any]]):
        """Delete all available (unattached) volumes with progress tracking"""
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}DELETING AVAILABLE EBS VOLUMES - THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*70}{Colors.END}")
        
        # Filter to only available volumes
        attached_volumes = [v for v in volumes if v['IsAttached']]
        available_volumes = [v for v in volumes if not v['IsAttached']]
        
        if attached_volumes:
            print(f"\n{Colors.YELLOW}INFO: {len(attached_volumes)} attached volumes will be skipped:{Colors.END}")
            for vol in attached_volumes[:5]:  # Show first 5
                attachment = vol['Attachments'][0]
                print(f"  {vol['VolumeId']} -> {attachment['InstanceId']} ({attachment['Device']})")
            if len(attached_volumes) > 5:
                print(f"  ... and {len(attached_volumes) - 5} more attached volumes")
        
        if not available_volumes:
            print(f"\n{Colors.YELLOW}No available volumes to delete. All volumes are attached.{Colors.END}")
            return
        
        print(f"\n{Colors.BLUE}Proceeding with {len(available_volumes)} available volumes...{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, volume in enumerate(available_volumes, 1):
            vol_id = volume['VolumeId']
            region = volume['Region']
            monthly_cost = volume['EstimatedMonthlyCost']
            
            print(f"\n[{i}/{len(available_volumes)}] Deleting {vol_id} in {region} (${monthly_cost:.2f}/month)...")
            
            if self.delete_volume(volume):
                print(f"{Colors.GREEN}✓ Successfully deleted {vol_id}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"{Colors.RED}✗ Failed to delete {vol_id}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
        
        # Final summary
        print(f"\n{Colors.BOLD}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        print(f"Successfully deleted: {Colors.GREEN}{deleted_count} volumes{Colors.END}")
        print(f"Failed to delete: {Colors.RED}{failed_count} volumes{Colors.END}")
        print(f"Skipped (attached): {Colors.YELLOW}{len(attached_volumes)} volumes{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if deleted_count > 0 and failed_count == 0:
            print(f"\n{Colors.GREEN}All available volumes deleted successfully!{Colors.END}")
        elif len(attached_volumes) > 0:
            print(f"\n{Colors.YELLOW}Note: To delete attached volumes, first detach them or terminate instances{Colors.END}")
    
    def run(self):
        """Main execution flow"""
        print(f"{Colors.BOLD}AWS EBS Volume Cleanup Tool{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all volumes
        volumes = self.list_all_volumes()
        
        if not volumes:
            print(f"\n{Colors.GREEN}No EBS volumes found! Nothing to delete.{Colors.END}")
            return
        
        # Calculate potential deletion impact
        available_volumes = [v for v in volumes if not v['IsAttached']]
        attached_volumes = [v for v in volumes if v['IsAttached']]
        
        if not available_volumes:
            print(f"\n{Colors.YELLOW}All {len(volumes)} volumes are attached to instances.{Colors.END}")
            print(f"{Colors.YELLOW}No volumes available for deletion.{Colors.END}")
            print(f"\n{Colors.BLUE}To delete attached volumes:{Colors.END}")
            print(f"  1. Stop or terminate the EC2 instances")
            print(f"  2. Detach the volumes manually")
            print(f"  3. Run this script again")
            return
        
        # Show deletion preview
        total_size = sum(vol['Size'] for vol in available_volumes)
        total_savings = sum(vol['EstimatedMonthlyCost'] for vol in available_volumes)
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION PREVIEW{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Available volumes to delete: {Colors.GREEN}{len(available_volumes)}{Colors.END}")
        print(f"Total size to be deleted: {Colors.GREEN}{total_size} GB{Colors.END}")
        print(f"Attached volumes (will be skipped): {Colors.YELLOW}{len(attached_volumes)}{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask for confirmation
        if self.get_user_confirmation("Do you want to proceed with deleting available volumes?"):
            # Double confirmation for safety
            if self.get_user_confirmation(f"Are you absolutely sure? This will permanently delete {len(available_volumes)} volumes!"):
                self.delete_available_volumes(volumes)
            else:
                print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")
        else:
            print(f"{Colors.BLUE}No volumes were deleted.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS EBS Volume Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 volume_cleanup.py                    # Use default AWS profile
  python3 volume_cleanup.py --profile dev      # Use specific profile
  
Features:
  - Lists all EBS volumes with detailed information
  - Shows estimated monthly costs and potential savings
  - Only deletes available (unattached) volumes for safety
  - Provides detailed breakdown by volume type
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help='AWS profile to use (default: uses default profile)'
    )
    
    args = parser.parse_args()
    
    try:
        cleaner = AWSVolumeCleaner(profile_name=args.profile)
        cleaner.run()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()