#!/usr/bin/env python3
"""
AWS EFS (Elastic File System) Cleanup Tool
Lists all EFS file systems and allows safe deletion with cost analysis.
EFS costs vary by storage class and can accumulate with unused file systems.
"""

import boto3
import argparse
import sys
from datetime import datetime, timezone, timedelta
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

class EFSCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS EFS cleaner"""
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
                efs = self.session.client('efs', region_name=region)
                efs.describe_file_systems(MaxItems=1)
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
    
    def get_efs_pricing(self, size_bytes: int, performance_mode: str, throughput_mode: str, provisioned_throughput: float = 0) -> float:
        """Calculate rough monthly cost for EFS file system"""
        # Convert bytes to GB
        size_gb = size_bytes / (1024**3) if size_bytes > 0 else 0
        
        # EFS pricing (simplified - actual pricing varies by region and storage class)
        # Standard storage: ~$0.30/GB-month
        # Standard-IA storage: ~$0.025/GB-month (for infrequently accessed files)
        standard_cost_per_gb = 0.30
        
        # Base storage cost
        storage_cost = size_gb * standard_cost_per_gb
        
        # Provisioned throughput cost
        # $6.00 per MB/s per month for provisioned throughput above baseline
        throughput_cost = 0
        if throughput_mode == 'provisioned' and provisioned_throughput > 0:
            # Baseline throughput is free (50 MB/s per TB of storage)
            baseline_throughput = max(1, size_gb / 1024 * 50)  # MB/s
            if provisioned_throughput > baseline_throughput:
                excess_throughput = provisioned_throughput - baseline_throughput
                throughput_cost = excess_throughput * 6.00
        
        total_monthly_cost = storage_cost + throughput_cost
        
        return total_monthly_cost
    
    def get_mount_targets(self, file_system_id: str, region: str) -> List[Dict[str, Any]]:
        """Get mount targets for an EFS file system"""
        try:
            efs = self.session.client('efs', region_name=region)
            
            mount_targets = efs.describe_mount_targets(FileSystemId=file_system_id)
            return mount_targets.get('MountTargets', [])
            
        except ClientError:
            return []
    
    def get_access_points(self, file_system_id: str, region: str) -> List[Dict[str, Any]]:
        """Get access points for an EFS file system"""
        try:
            efs = self.session.client('efs', region_name=region)
            
            access_points = efs.describe_access_points(FileSystemId=file_system_id)
            return access_points.get('AccessPoints', [])
            
        except ClientError:
            return []
    
    def get_efs_metrics(self, file_system_id: str, region: str) -> Dict[str, Any]:
        """Get CloudWatch metrics for EFS file system"""
        try:
            cloudwatch = self.session.client('cloudwatch', region_name=region)
            
            # Get metrics for the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            # Client connections metric
            connections_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/EFS',
                MetricName='ClientConnections',
                Dimensions=[{'Name': 'FileSystemId', 'Value': file_system_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,  # Daily
                Statistics=['Sum', 'Average']
            )
            
            # Data read/write metrics
            read_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/EFS',
                MetricName='DataReadIOBytes',
                Dimensions=[{'Name': 'FileSystemId', 'Value': file_system_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Sum']
            )
            
            write_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/EFS',
                MetricName='DataWriteIOBytes',
                Dimensions=[{'Name': 'FileSystemId', 'Value': file_system_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Sum']
            )
            
            # Process metrics
            total_connections = sum(point['Sum'] for point in connections_response['Datapoints'])
            avg_connections = sum(point['Average'] for point in connections_response['Datapoints']) / len(connections_response['Datapoints']) if connections_response['Datapoints'] else 0
            
            total_read_bytes = sum(point['Sum'] for point in read_response['Datapoints'])
            total_write_bytes = sum(point['Sum'] for point in write_response['Datapoints'])
            
            return {
                'total_connections': total_connections,
                'avg_connections': avg_connections,
                'total_read_bytes': total_read_bytes,
                'total_write_bytes': total_write_bytes,
                'has_activity': total_connections > 0 or total_read_bytes > 0 or total_write_bytes > 0
            }
            
        except ClientError:
            return {
                'total_connections': 0,
                'avg_connections': 0,
                'total_read_bytes': 0,
                'total_write_bytes': 0,
                'has_activity': False
            }
    
    def check_efs_safety(self, efs_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if EFS file system appears to be important or in use"""
        fs_name = efs_info.get('name', efs_info['file_system_id'])
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary',
            'shared', 'data', 'backup', 'content', 'web'
        ]
        
        name_lower = fs_name.lower()
        for pattern in important_patterns:
            if pattern in name_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
                break
        
        # Check if file system has mount targets (actively accessible)
        mount_target_count = efs_info.get('mount_target_count', 0)
        if mount_target_count > 0:
            safety_warnings.append(f"Has {mount_target_count} mount targets - actively accessible")
        
        # Check if file system has access points
        access_point_count = efs_info.get('access_point_count', 0)
        if access_point_count > 0:
            safety_warnings.append(f"Has {access_point_count} access points")
        
        # Check if file system has recent activity
        metrics = efs_info.get('metrics', {})
        if metrics.get('has_activity'):
            if metrics.get('avg_connections', 0) > 0:
                safety_warnings.append(f"Recent connections: {metrics['avg_connections']:.1f} avg/day")
            
            total_io = metrics.get('total_read_bytes', 0) + metrics.get('total_write_bytes', 0)
            if total_io > 0:
                io_gb = total_io / (1024**3)
                safety_warnings.append(f"Recent I/O activity: {io_gb:.2f} GB in 30 days")
        
        # Check if file system has provisioned throughput (costs extra)
        if efs_info.get('throughput_mode') == 'provisioned':
            provisioned = efs_info.get('provisioned_throughput_in_mibps', 0)
            safety_warnings.append(f"Provisioned throughput: {provisioned} MB/s (costs extra)")
        
        # Check if file system is encrypted (more likely to be important)
        if efs_info.get('encrypted'):
            safety_warnings.append("File system is encrypted")
        
        # Check if file system has lifecycle policy (automatic cost optimization)
        if efs_info.get('lifecycle_policies'):
            policy_count = len(efs_info['lifecycle_policies'])
            safety_warnings.append(f"Has {policy_count} lifecycle policies")
        
        # Check if recently created (within 7 days)
        created_time = efs_info['creation_time']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
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
    
    def list_efs_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all EFS file systems in a specific region"""
        try:
            efs = self.session.client('efs', region_name=region)
            
            file_systems = []
            paginator = efs.get_paginator('describe_file_systems')
            
            for page in paginator.paginate():
                for fs in page['FileSystems']:
                    file_system_id = fs['FileSystemId']
                    
                    # Get mount targets
                    mount_targets = self.get_mount_targets(file_system_id, region)
                    
                    # Get access points
                    access_points = self.get_access_points(file_system_id, region)
                    
                    # Get metrics
                    metrics = self.get_efs_metrics(file_system_id, region)
                    
                    # Get lifecycle policies
                    try:
                        lifecycle_response = efs.describe_lifecycle_configuration(FileSystemId=file_system_id)
                        lifecycle_policies = lifecycle_response.get('LifecyclePolicies', [])
                    except ClientError:
                        lifecycle_policies = []
                    
                    # Calculate pricing
                    monthly_cost = self.get_efs_pricing(
                        fs['SizeInBytes']['Value'],
                        fs['PerformanceMode'],
                        fs['ThroughputMode'],
                        fs.get('ProvisionedThroughputInMibps', 0)
                    )
                    
                    # Get name from tags
                    name = file_system_id
                    for tag in fs.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
                    
                    fs_info = {
                        'file_system_id': file_system_id,
                        'name': name,
                        'region': region,
                        'creation_time': fs['CreationTime'],
                        'life_cycle_state': fs['LifeCycleState'],
                        'number_of_mount_targets': fs['NumberOfMountTargets'],
                        'size_bytes': fs['SizeInBytes']['Value'],
                        'performance_mode': fs['PerformanceMode'],
                        'throughput_mode': fs['ThroughputMode'],
                        'provisioned_throughput_in_mibps': fs.get('ProvisionedThroughputInMibps', 0),
                        'encrypted': fs.get('Encrypted', False),
                        'kms_key_id': fs.get('KmsKeyId'),
                        'availability_zone_name': fs.get('AvailabilityZoneName'),  # One Zone EFS
                        'mount_targets': mount_targets,
                        'mount_target_count': len(mount_targets),
                        'access_points': access_points,
                        'access_point_count': len(access_points),
                        'lifecycle_policies': lifecycle_policies,
                        'metrics': metrics,
                        'monthly_cost': monthly_cost
                    }
                    
                    # Add safety check
                    fs_info['safety'] = self.check_efs_safety(fs_info)
                    
                    file_systems.append(fs_info)
            
            return file_systems
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing EFS file systems in {region}: {e}{Colors.END}")
            return []
    
    def format_fs_info(self, fs: Dict[str, Any]) -> str:
        """Format file system information for display"""
        name = fs['name'][:20] if len(fs['name']) > 20 else fs['name']
        fs_id = fs['file_system_id']
        region = fs['region']
        size = self.format_size(fs['size_bytes'])
        state = fs['life_cycle_state'][:10]
        
        performance_mode = fs['performance_mode'][:8]
        throughput_mode = fs['throughput_mode'][:8]
        
        mount_targets = fs['mount_target_count']
        access_points = fs['access_point_count']
        monthly_cost = fs['monthly_cost']
        
        # Activity indicator
        metrics = fs['metrics']
        if metrics.get('has_activity'):
            activity = f"{metrics['avg_connections']:.0f} conn"
        else:
            activity = "No activity"
        
        created_time = fs['creation_time']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Encryption indicator
        encryption = "✓" if fs['encrypted'] else "✗"
        
        # Safety indicator
        if fs['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {name:<20} | {fs_id:<17} | {region:<12} | {size:<8} | {state:<10} | {performance_mode:<8} | {throughput_mode:<8} | {mount_targets:>2} | {access_points:>2} | {activity:<12} | {encryption:<3} | ${monthly_cost:>6.2f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_file_systems(self) -> List[Dict[str, Any]]:
        """List all EFS file systems across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*180}{Colors.END}")
        print(f"{Colors.BLUE}Scanning EFS File Systems across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*180}{Colors.END}")
        
        all_file_systems = []
        total_cost = 0
        total_size = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            file_systems = self.list_efs_in_region(region)
            
            if file_systems:
                region_cost = sum(fs['monthly_cost'] for fs in file_systems)
                region_size = sum(fs['size_bytes'] for fs in file_systems)
                
                mounted_count = sum(1 for fs in file_systems if fs['mount_target_count'] > 0)
                
                print(f"{Colors.GREEN}Found {len(file_systems)} file systems{Colors.END}")
                print(f"  With mount targets: {mounted_count}")
                print(f"  Total size: {self.format_size(region_size)}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                total_size += region_size
                all_file_systems.extend(file_systems)
            else:
                print(f"{Colors.GREEN}No file systems found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for fs in all_file_systems if fs['safety']['is_risky'])
        inactive_count = sum(1 for fs in all_file_systems if not fs['metrics'].get('has_activity', False))
        unmounted_count = sum(1 for fs in all_file_systems if fs['mount_target_count'] == 0)
        
        print(f"\n{Colors.BOLD}EFS FILE SYSTEMS SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*180}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total file systems found: {Colors.YELLOW}{len(all_file_systems)}{Colors.END}")
        print(f"File systems with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive file systems: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Unmounted file systems: {Colors.YELLOW}{unmounted_count}{Colors.END}")
        print(f"Total storage size: {Colors.YELLOW}{self.format_size(total_size)}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_file_systems:
            print(f"\n{Colors.BOLD}FILE SYSTEM DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*180}{Colors.END}")
            print(f"  {'Name':<20} | {'File System ID':<17} | {'Region':<12} | {'Size':<8} | {'State':<10} | {'Perf':<8} | {'Thru':<8} | {'MT':<2} | {'AP':<2} | {'Activity':<12} | {'Enc':<3} | {'Cost':<7} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*17} | {'-'*12} | {'-'*8} | {'-'*10} | {'-'*8} | {'-'*8} | {'-'*2} | {'-'*2} | {'-'*12} | {'-'*3} | {'-'*7} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first), then by safety risk
            sorted_file_systems = sorted(all_file_systems, key=lambda x: (-x['monthly_cost'], not x['safety']['is_risky']))
            
            for fs in sorted_file_systems:
                print(self.format_fs_info(fs))
                
                # Show safety warnings
                if fs['safety']['warnings']:
                    for warning in fs['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by performance mode
            print(f"\n{Colors.BOLD}BREAKDOWN BY PERFORMANCE MODE{Colors.END}")
            performance_modes = {}
            for fs in all_file_systems:
                mode = fs['performance_mode']
                if mode not in performance_modes:
                    performance_modes[mode] = {'count': 0, 'cost': 0, 'size': 0}
                performance_modes[mode]['count'] += 1
                performance_modes[mode]['cost'] += fs['monthly_cost']
                performance_modes[mode]['size'] += fs['size_bytes']
            
            for mode, stats in sorted(performance_modes.items()):
                print(f"  {mode:<15}: {stats['count']} file systems, {self.format_size(stats['size'])}, ${stats['cost']:.2f}/month")
        
        return all_file_systems
    
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
    
    def show_fs_selection_menu(self, file_systems: List[Dict[str, Any]]) -> List[str]:
        """Show menu for file system selection"""
        if not file_systems:
            return []
        
        print(f"\n{Colors.BOLD}SELECT FILE SYSTEMS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter file system numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all file systems")
        print("Or enter 'inactive' to select file systems with no recent activity")
        print("Or enter 'unmounted' to select file systems with no mount targets")
        print("Or enter 'safe' to select only file systems without warnings")
        print("")
        
        # Show numbered list
        inactive_fs = []
        safe_fs = []
        unmounted_fs = []
        
        for i, fs in enumerate(file_systems, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if fs['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            monthly_cost = fs['monthly_cost']
            size = self.format_size(fs['size_bytes'])
            
            activity_indicator = ""
            if not fs['metrics'].get('has_activity', False):
                activity_indicator = f"{Colors.YELLOW}(INACTIVE){Colors.END}"
                inactive_fs.append(fs['file_system_id'])
            
            if fs['mount_target_count'] == 0:
                unmounted_fs.append(fs['file_system_id'])
            
            if not fs['safety']['is_risky']:
                safe_fs.append(fs['file_system_id'])
            
            mount_info = f"{fs['mount_target_count']} MT" if fs['mount_target_count'] > 0 else "No MT"
            
            print(f"{i:2d}. {fs['name']:<25} | {fs['region']:<12} | {size:<8} | {mount_info:<5} | ${monthly_cost:>6.2f}/mo | {safety_indicator} {activity_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [fs['file_system_id'] for fs in file_systems]
            elif choice == 'inactive':
                if inactive_fs:
                    return inactive_fs
                else:
                    print(f"{Colors.RED}No inactive file systems found{Colors.END}")
                    continue
            elif choice == 'unmounted':
                if unmounted_fs:
                    return unmounted_fs
                else:
                    print(f"{Colors.RED}No unmounted file systems found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_fs:
                    return safe_fs
                else:
                    print(f"{Colors.RED}No 'safe' file systems found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(file_systems):
                            selected.append(file_systems[idx-1]['file_system_id'])
                        else:
                            print(f"{Colors.RED}Invalid file system number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'inactive', 'unmounted', or 'safe'{Colors.END}")
    
    def delete_mount_targets(self, mount_targets: List[Dict[str, Any]], region: str) -> bool:
        """Delete all mount targets for a file system"""
        if not mount_targets:
            return True
        
        try:
            efs = self.session.client('efs', region_name=region)
            
            print(f"    Deleting {len(mount_targets)} mount targets...")
            for mt in mount_targets:
                mt_id = mt['MountTargetId']
                print(f"      Deleting mount target {mt_id}")
                efs.delete_mount_target(MountTargetId=mt_id)
            
            # Wait for mount targets to be deleted
            print("    Waiting for mount targets to be deleted...")
            time.sleep(30)  # EFS mount target deletion takes time
            
            return True
            
        except ClientError as e:
            print(f"    {Colors.RED}Error deleting mount targets: {e}{Colors.END}")
            return False
    
    def delete_access_points(self, access_points: List[Dict[str, Any]], region: str) -> bool:
        """Delete all access points for a file system"""
        if not access_points:
            return True
        
        try:
            efs = self.session.client('efs', region_name=region)
            
            print(f"    Deleting {len(access_points)} access points...")
            for ap in access_points:
                ap_id = ap['AccessPointId']
                print(f"      Deleting access point {ap_id}")
                efs.delete_access_point(AccessPointId=ap_id)
            
            # Access points delete faster than mount targets
            time.sleep(10)
            
            return True
            
        except ClientError as e:
            print(f"    {Colors.RED}Error deleting access points: {e}{Colors.END}")
            return False
    
    def delete_file_system(self, fs: Dict[str, Any], dry_run: bool = False) -> bool:
        """Delete an EFS file system"""
        fs_id = fs['file_system_id']
        region = fs['region']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete file system {fs_id}{Colors.END}")
            return True
        
        try:
            efs = self.session.client('efs', region_name=region)
            
            # First delete access points
            if fs['access_points']:
                if not self.delete_access_points(fs['access_points'], region):
                    return False
            
            # Then delete mount targets
            if fs['mount_targets']:
                if not self.delete_mount_targets(fs['mount_targets'], region):
                    return False
            
            # Finally delete the file system
            print(f"    Deleting file system {fs_id}...")
            efs.delete_file_system(FileSystemId=fs_id)
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'FileSystemNotFound':
                print(f"  {Colors.YELLOW}File system {fs_id} not found (already deleted?){Colors.END}")
                return True
            elif error_code == 'FileSystemInUse':
                print(f"  {Colors.RED}File system {fs_id} is still in use (mount targets may still exist){Colors.END}")
                return False
            else:
                print(f"  {Colors.RED}Error deleting {fs_id}: {e}{Colors.END}")
                return False
    
    def delete_file_systems(self, file_systems: List[Dict[str, Any]], selected_fs_ids: List[str], dry_run: bool = False):
        """Delete selected file systems"""
        fs_to_delete = [fs for fs in file_systems if fs['file_system_id'] in selected_fs_ids]
        
        if not fs_to_delete:
            print(f"{Colors.YELLOW}No file systems selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING EFS FILE SYSTEMS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS WILL DELETE ALL DATA IN THE FILE SYSTEMS!{Colors.END}")
            print(f"{Colors.RED}THIS ACTION CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, fs in enumerate(fs_to_delete, 1):
            fs_id = fs['file_system_id']
            name = fs['name']
            region = fs['region']
            size = self.format_size(fs['size_bytes'])
            monthly_cost = fs['monthly_cost']
            
            print(f"\n[{i}/{len(fs_to_delete)}] Processing file system: {name} ({fs_id})")
            print(f"  Region: {region}, Size: {size}, Cost: ${monthly_cost:.2f}/month")
            print(f"  Mount targets: {fs['mount_target_count']}, Access points: {fs['access_point_count']}")
            
            # Show warnings
            if fs['safety']['warnings']:
                for warning in fs['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_file_system(fs, dry_run):
                success_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {success_text} {fs_id}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {fs_id}{Colors.END}")
                failed_count += 1
            
            # Longer delay for EFS operations
            if not dry_run:
                time.sleep(5)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} file systems{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} file systems{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            print(f"\n{Colors.RED}Warning: All data in the deleted file systems is permanently lost!{Colors.END}")
            print(f"{Colors.YELLOW}Note: File system deletion may take several minutes to complete.{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS EFS File System Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all file systems
        file_systems = self.list_all_file_systems()
        
        if not file_systems:
            print(f"\n{Colors.GREEN}No EFS file systems found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(fs['monthly_cost'] for fs in file_systems)
        risky_count = sum(1 for fs in file_systems if fs['safety']['is_risky'])
        inactive_count = sum(1 for fs in file_systems if not fs['metrics'].get('has_activity', False))
        unmounted_count = sum(1 for fs in file_systems if fs['mount_target_count'] == 0)
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total file systems: {Colors.BLUE}{len(file_systems)}{Colors.END}")
        print(f"File systems with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive file systems: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Unmounted file systems: {Colors.YELLOW}{unmounted_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  EFS deletion will permanently destroy all data!{Colors.END}")
            print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with file system selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select file systems
        selected_fs_ids = self.show_fs_selection_menu(file_systems)
        
        if not selected_fs_ids:
            print(f"{Colors.BLUE}No file systems selected. Exiting.{Colors.END}")
            return
        
        selected_fs = [fs for fs in file_systems if fs['file_system_id'] in selected_fs_ids]
        selected_cost = sum(fs['monthly_cost'] for fs in selected_fs)
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected file systems: {Colors.YELLOW}{len(selected_fs)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these file systems and ALL THEIR DATA?"
        if self.get_user_confirmation(final_question):
            self.delete_file_systems(file_systems, selected_fs_ids, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS EFS File System Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 efs_cleanup.py                          # Use default AWS profile
  python3 efs_cleanup.py --profile dev            # Use specific profile
  python3 efs_cleanup.py --dry-run                # Test mode - no actual deletions
  
Features:
  - Lists all EFS file systems with size and cost analysis
  - Shows mount targets and access point information
  - Identifies inactive file systems with no recent I/O
  - Safety warnings for mounted and encrypted file systems
  - Automatically deletes mount targets and access points
  - Cost varies by size and performance mode ($0.30/GB-month for standard)
  
Warning:
  EFS deletion permanently destroys all data and cannot be undone!
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
        cleaner = EFSCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()