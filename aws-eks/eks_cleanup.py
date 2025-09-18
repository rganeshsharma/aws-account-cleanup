#!/usr/bin/env python3
"""
AWS EKS (Elastic Kubernetes Service) Cleanup Tool
Lists all EKS clusters and allows safe deletion with cost analysis.
EKS clusters cost $0.10/hour (~$72/month) plus worker node costs, making cleanup very valuable.
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

class EKSCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS EKS cleaner"""
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
                eks = self.session.client('eks', region_name=region)
                eks.list_clusters(maxResults=1)
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
    
    def get_eks_pricing(self, cluster_hours: int = 24*30) -> float:
        """Calculate EKS cluster control plane cost"""
        # EKS control plane costs $0.10 per hour regardless of cluster size
        hourly_cost = 0.10
        monthly_cost = hourly_cost * cluster_hours
        return monthly_cost
    
    def estimate_node_group_cost(self, node_group: Dict[str, Any], region: str) -> float:
        """Estimate cost for an EKS node group"""
        # This is a rough estimation - actual costs depend on instance types and usage
        instance_types = node_group.get('instanceTypes', ['m5.large'])
        min_size = node_group.get('scalingConfig', {}).get('minSize', 0)
        desired_capacity = node_group.get('scalingConfig', {}).get('desiredSize', min_size)
        
        # Rough pricing for common instance types (hourly)
        instance_pricing = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            't3.large': 0.0832,
            't3.xlarge': 0.1664,
            'm5.large': 0.096,
            'm5.xlarge': 0.192,
            'm5.2xlarge': 0.384,
            'm5.4xlarge': 0.768,
            'c5.large': 0.085,
            'c5.xlarge': 0.17,
            'r5.large': 0.126,
            'r5.xlarge': 0.252,
        }
        
        # Use first instance type for estimation
        primary_instance_type = instance_types[0] if instance_types else 'm5.large'
        hourly_cost_per_instance = instance_pricing.get(primary_instance_type, 0.1)
        
        # Calculate monthly cost for desired capacity
        monthly_cost = hourly_cost_per_instance * desired_capacity * 24 * 30
        
        return monthly_cost
    
    def get_node_groups(self, cluster_name: str, region: str) -> List[Dict[str, Any]]:
        """Get all node groups for an EKS cluster"""
        try:
            eks = self.session.client('eks', region_name=region)
            
            # List node groups
            node_groups_response = eks.list_nodegroups(clusterName=cluster_name)
            node_group_names = node_groups_response.get('nodegroups', [])
            
            node_groups = []
            for ng_name in node_group_names:
                try:
                    ng_details = eks.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=ng_name
                    )
                    node_group = ng_details['nodegroup']
                    
                    # Add cost estimation
                    node_group['estimated_monthly_cost'] = self.estimate_node_group_cost(node_group, region)
                    
                    node_groups.append(node_group)
                except ClientError:
                    continue
            
            return node_groups
            
        except ClientError:
            return []
    
    def get_fargate_profiles(self, cluster_name: str, region: str) -> List[Dict[str, Any]]:
        """Get all Fargate profiles for an EKS cluster"""
        try:
            eks = self.session.client('eks', region_name=region)
            
            # List Fargate profiles
            fargate_response = eks.list_fargate_profiles(clusterName=cluster_name)
            fargate_profile_names = fargate_response.get('fargateProfileNames', [])
            
            fargate_profiles = []
            for fp_name in fargate_profile_names:
                try:
                    fp_details = eks.describe_fargate_profile(
                        clusterName=cluster_name,
                        fargateProfileName=fp_name
                    )
                    fargate_profile = fp_details['fargateProfile']
                    
                    # Fargate pricing is per vCPU-second and GB-second
                    # Rough estimate: $0.04048 per vCPU per hour + $0.004445 per GB per hour
                    # This is difficult to estimate without knowing actual workloads
                    fargate_profile['estimated_monthly_cost'] = 20.0  # Conservative estimate
                    
                    fargate_profiles.append(fargate_profile)
                except ClientError:
                    continue
            
            return fargate_profiles
            
        except ClientError:
            return []
    
    def get_cluster_addons(self, cluster_name: str, region: str) -> List[Dict[str, Any]]:
        """Get all add-ons for an EKS cluster"""
        try:
            eks = self.session.client('eks', region_name=region)
            
            # List add-ons
            addons_response = eks.list_addons(clusterName=cluster_name)
            addon_names = addons_response.get('addons', [])
            
            addons = []
            for addon_name in addon_names:
                try:
                    addon_details = eks.describe_addon(
                        clusterName=cluster_name,
                        addonName=addon_name
                    )
                    addons.append(addon_details['addon'])
                except ClientError:
                    continue
            
            return addons
            
        except ClientError:
            return []
    
    def check_cluster_activity(self, cluster_name: str, region: str) -> Dict[str, Any]:
        """Check for cluster activity indicators"""
        try:
            # We can't easily check for running pods without kubectl access
            # But we can check for recent API activity via CloudTrail
            cloudtrail = self.session.client('cloudtrail', region_name=region)
            
            # Look for EKS API activity in the last 7 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=7)
            
            events = cloudtrail.lookup_events(
                LookupAttributes=[
                    {
                        'AttributeKey': 'ResourceName',
                        'AttributeValue': cluster_name
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                MaxItems=20
            )
            
            api_calls = []
            for event in events.get('Events', []):
                event_name = event.get('EventName', '')
                if any(api in event_name.lower() for api in ['create', 'delete', 'update', 'describe']):
                    api_calls.append({
                        'event_name': event_name,
                        'event_time': event['EventTime']
                    })
            
            return {
                'recent_api_calls': len(api_calls),
                'last_activity': max([event['event_time'] for event in api_calls]) if api_calls else None,
                'has_recent_activity': len(api_calls) > 0
            }
            
        except ClientError:
            return {
                'recent_api_calls': 0,
                'last_activity': None,
                'has_recent_activity': False
            }
    
    def check_cluster_safety(self, cluster_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if EKS cluster appears to be important or in use"""
        cluster_name = cluster_info['name']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary',
            'staging', 'qa', 'test', 'development', 'dev'
        ]
        
        name_lower = cluster_name.lower()
        for pattern in important_patterns:
            if pattern in name_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
                break
        
        # Check if cluster has node groups
        node_group_count = len(cluster_info.get('node_groups', []))
        if node_group_count > 0:
            total_nodes = sum(
                ng.get('scalingConfig', {}).get('desiredSize', 0) 
                for ng in cluster_info['node_groups']
            )
            safety_warnings.append(f"Has {node_group_count} node groups with {total_nodes} total nodes")
        
        # Check if cluster has Fargate profiles
        fargate_profile_count = len(cluster_info.get('fargate_profiles', []))
        if fargate_profile_count > 0:
            safety_warnings.append(f"Has {fargate_profile_count} Fargate profiles")
        
        # Check if cluster has add-ons
        addon_count = len(cluster_info.get('addons', []))
        if addon_count > 0:
            addon_names = [addon['addonName'] for addon in cluster_info['addons']]
            safety_warnings.append(f"Has {addon_count} add-ons: {', '.join(addon_names[:3])}")
        
        # Check for recent activity
        activity = cluster_info.get('activity', {})
        if activity.get('has_recent_activity'):
            api_calls = activity['recent_api_calls']
            safety_warnings.append(f"Recent activity: {api_calls} API calls in 7 days")
        
        # Check cluster status
        if cluster_info['status'] == 'ACTIVE':
            safety_warnings.append("Cluster is ACTIVE")
        
        # Check if cluster is private (more likely to be important)
        endpoint_config = cluster_info.get('endpoint_config', {})
        if not endpoint_config.get('publicAccess', True):
            safety_warnings.append("Private cluster (no public API endpoint)")
        
        # Check if cluster has encryption enabled
        encryption_config = cluster_info.get('encryptionConfig', [])
        if encryption_config:
            safety_warnings.append("Encryption enabled")
        
        # Check if recently created (within 7 days)
        created_time = cluster_info['created_at']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def list_eks_clusters_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all EKS clusters in a specific region"""
        try:
            eks = self.session.client('eks', region_name=region)
            
            clusters = []
            
            # List clusters
            clusters_response = eks.list_clusters()
            cluster_names = clusters_response.get('clusters', [])
            
            for cluster_name in cluster_names:
                try:
                    # Get cluster details
                    cluster_response = eks.describe_cluster(name=cluster_name)
                    cluster = cluster_response['cluster']
                    
                    # Get node groups
                    node_groups = self.get_node_groups(cluster_name, region)
                    
                    # Get Fargate profiles
                    fargate_profiles = self.get_fargate_profiles(cluster_name, region)
                    
                    # Get add-ons
                    addons = self.get_cluster_addons(cluster_name, region)
                    
                    # Check for recent activity
                    activity = self.check_cluster_activity(cluster_name, region)
                    
                    # Calculate total monthly cost
                    control_plane_cost = self.get_eks_pricing()
                    node_group_cost = sum(ng.get('estimated_monthly_cost', 0) for ng in node_groups)
                    fargate_cost = sum(fp.get('estimated_monthly_cost', 0) for fp in fargate_profiles)
                    total_monthly_cost = control_plane_cost + node_group_cost + fargate_cost
                    
                    cluster_info = {
                        'name': cluster_name,
                        'region': region,
                        'arn': cluster['arn'],
                        'version': cluster['version'],
                        'status': cluster['status'],
                        'created_at': cluster['createdAt'],
                        'endpoint': cluster['endpoint'],
                        'role_arn': cluster['roleArn'],
                        'vpc_config': cluster.get('resourcesVpcConfig', {}),
                        'endpoint_config': cluster.get('endpointConfig', {}),
                        'logging': cluster.get('logging', {}),
                        'encryption_config': cluster.get('encryptionConfig', []),
                        'platform_version': cluster.get('platformVersion', ''),
                        'tags': cluster.get('tags', {}),
                        'node_groups': node_groups,
                        'fargate_profiles': fargate_profiles,
                        'addons': addons,
                        'activity': activity,
                        'control_plane_cost': control_plane_cost,
                        'node_group_cost': node_group_cost,
                        'fargate_cost': fargate_cost,
                        'total_monthly_cost': total_monthly_cost
                    }
                    
                    # Add safety check
                    cluster_info['safety'] = self.check_cluster_safety(cluster_info)
                    
                    clusters.append(cluster_info)
                    
                except ClientError as e:
                    print(f"    {Colors.YELLOW}Warning: Cannot access cluster {cluster_name}: {e}{Colors.END}")
                    continue
            
            return clusters
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing EKS clusters in {region}: {e}{Colors.END}")
            return []
    
    def format_cluster_info(self, cluster: Dict[str, Any]) -> str:
        """Format cluster information for display"""
        name = cluster['name'][:20] if len(cluster['name']) > 20 else cluster['name']
        region = cluster['region']
        version = cluster['version']
        status = cluster['status'][:8]
        
        node_group_count = len(cluster['node_groups'])
        fargate_count = len(cluster['fargate_profiles'])
        addon_count = len(cluster['addons'])
        
        # Calculate total nodes
        total_nodes = sum(
            ng.get('scalingConfig', {}).get('desiredSize', 0) 
            for ng in cluster['node_groups']
        )
        
        total_monthly_cost = cluster['total_monthly_cost']
        
        # Activity indicator
        activity = cluster['activity']
        if activity.get('has_recent_activity'):
            activity_indicator = f"{activity['recent_api_calls']} calls"
        else:
            activity_indicator = "No activity"
        
        created_time = cluster['created_at']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Public/private indicator
        endpoint_config = cluster.get('endpoint_config', {})
        access_type = "Public" if endpoint_config.get('publicAccess', True) else "Private"
        
        # Safety indicator
        if cluster['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {name:<20} | {region:<12} | {version:<8} | {status:<8} | {node_group_count:>2} | {total_nodes:>3} | {fargate_count:>2} | {addon_count:>2} | {access_type:<7} | {activity_indicator:<12} | ${total_monthly_cost:>7.0f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_clusters(self) -> List[Dict[str, Any]]:
        """List all EKS clusters across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*160}{Colors.END}")
        print(f"{Colors.BLUE}Scanning EKS Clusters across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*160}{Colors.END}")
        
        all_clusters = []
        total_cost = 0
        total_nodes = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            clusters = self.list_eks_clusters_in_region(region)
            
            if clusters:
                region_cost = sum(cluster['total_monthly_cost'] for cluster in clusters)
                region_nodes = sum(
                    sum(ng.get('scalingConfig', {}).get('desiredSize', 0) for ng in cluster['node_groups'])
                    for cluster in clusters
                )
                region_fargate = sum(len(cluster['fargate_profiles']) for cluster in clusters)
                
                print(f"{Colors.GREEN}Found {len(clusters)} clusters{Colors.END}")
                print(f"  Total nodes: {region_nodes}")
                print(f"  Fargate profiles: {region_fargate}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                total_nodes += region_nodes
                all_clusters.extend(clusters)
            else:
                print(f"{Colors.GREEN}No clusters found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for cluster in all_clusters if cluster['safety']['is_risky'])
        inactive_count = sum(1 for cluster in all_clusters if not cluster['activity'].get('has_recent_activity', False))
        
        print(f"\n{Colors.BOLD}EKS CLUSTERS SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*160}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total clusters found: {Colors.YELLOW}{len(all_clusters)}{Colors.END}")
        print(f"Clusters with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive clusters: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Total worker nodes: {Colors.YELLOW}{total_nodes}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_clusters:
            print(f"\n{Colors.BOLD}CLUSTER DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*160}{Colors.END}")
            print(f"  {'Cluster Name':<20} | {'Region':<12} | {'Version':<8} | {'Status':<8} | {'NG':<2} | {'Nodes':<3} | {'FG':<2} | {'Add':<2} | {'Access':<7} | {'Activity':<12} | {'Cost':<8} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*12} | {'-'*8} | {'-'*8} | {'-'*2} | {'-'*3} | {'-'*2} | {'-'*2} | {'-'*7} | {'-'*12} | {'-'*8} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first)
            sorted_clusters = sorted(all_clusters, key=lambda x: -x['total_monthly_cost'])
            
            for cluster in sorted_clusters:
                print(self.format_cluster_info(cluster))
                
                # Show safety warnings
                if cluster['safety']['warnings']:
                    for warning in cluster['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show cost breakdown
            print(f"\n{Colors.BOLD}COST BREAKDOWN{Colors.END}")
            total_control_plane = sum(c['control_plane_cost'] for c in all_clusters)
            total_node_groups = sum(c['node_group_cost'] for c in all_clusters)
            total_fargate = sum(c['fargate_cost'] for c in all_clusters)
            
            print(f"  Control Plane: ${total_control_plane:.2f}/month ({len(all_clusters)} clusters × $72/month)")
            print(f"  Node Groups  : ${total_node_groups:.2f}/month")
            print(f"  Fargate      : ${total_fargate:.2f}/month")
            print(f"  Total        : ${total_cost:.2f}/month")
        
        return all_clusters
    
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
    
    def show_cluster_selection_menu(self, clusters: List[Dict[str, Any]]) -> List[str]:
        """Show menu for cluster selection"""
        if not clusters:
            return []
        
        print(f"\n{Colors.BOLD}SELECT CLUSTERS TO DELETE{Colors.END}")
        print(f"{Colors.BLUE}{'='*60}{Colors.END}")
        print("Enter cluster numbers separated by commas (e.g., 1,3,5)")
        print("Or enter 'all' to select all clusters")
        print("Or enter 'inactive' to select clusters with no recent activity")
        print("Or enter 'empty' to select clusters with no node groups")
        print("Or enter 'safe' to select only clusters without warnings")
        print("")
        
        # Show numbered list
        inactive_clusters = []
        safe_clusters = []
        empty_clusters = []
        
        for i, cluster in enumerate(clusters, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if cluster['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            monthly_cost = cluster['total_monthly_cost']
            
            node_count = sum(ng.get('scalingConfig', {}).get('desiredSize', 0) for ng in cluster['node_groups'])
            
            activity_indicator = ""
            if not cluster['activity'].get('has_recent_activity', False):
                activity_indicator = f"{Colors.YELLOW}(INACTIVE){Colors.END}"
                inactive_clusters.append(cluster['name'])
            
            if len(cluster['node_groups']) == 0:
                empty_clusters.append(cluster['name'])
            
            if not cluster['safety']['is_risky']:
                safe_clusters.append(cluster['name'])
            
            node_info = f"{len(cluster['node_groups'])} NG, {node_count} nodes"
            
            print(f"{i:2d}. {cluster['name']:<25} | {cluster['region']:<12} | {node_info:<15} | ${monthly_cost:>7.0f}/mo | {safety_indicator} {activity_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [cluster['name'] for cluster in clusters]
            elif choice == 'inactive':
                if inactive_clusters:
                    return inactive_clusters
                else:
                    print(f"{Colors.RED}No inactive clusters found{Colors.END}")
                    continue
            elif choice == 'empty':
                if empty_clusters:
                    return empty_clusters
                else:
                    print(f"{Colors.RED}No empty clusters found{Colors.END}")
                    continue
            elif choice == 'safe':
                if safe_clusters:
                    return safe_clusters
                else:
                    print(f"{Colors.RED}No 'safe' clusters found (all have warnings){Colors.END}")
                    continue
            elif choice == '':
                return []
            else:
                try:
                    indices = [int(x.strip()) for x in choice.split(',')]
                    selected = []
                    
                    for idx in indices:
                        if 1 <= idx <= len(clusters):
                            selected.append(clusters[idx-1]['name'])
                        else:
                            print(f"{Colors.RED}Invalid cluster number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'inactive', 'empty', or 'safe'{Colors.END}")
    
    def delete_node_groups(self, cluster_name: str, node_groups: List[Dict[str, Any]], region: str) -> bool:
        """Delete all node groups in a cluster"""
        if not node_groups:
            return True
        
        try:
            eks = self.session.client('eks', region_name=region)
            
            print(f"    Deleting {len(node_groups)} node groups...")
            for ng in node_groups:
                ng_name = ng['nodegroupName']
                print(f"      Deleting node group {ng_name}")
                eks.delete_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )
            
            # Wait for node groups to start deleting
            print("    Waiting for node groups to begin deletion...")
            time.sleep(30)
            
            return True
            
        except ClientError as e:
            print(f"    {Colors.RED}Error deleting node groups: {e}{Colors.END}")
            return False
    
    def delete_fargate_profiles(self, cluster_name: str, fargate_profiles: List[Dict[str, Any]], region: str) -> bool:
        """Delete all Fargate profiles in a cluster"""
        if not fargate_profiles:
            return True
        
        try:
            eks = self.session.client('eks', region_name=region)
            
            print(f"    Deleting {len(fargate_profiles)} Fargate profiles...")
            for fp in fargate_profiles:
                fp_name = fp['fargateProfileName']
                print(f"      Deleting Fargate profile {fp_name}")
                eks.delete_fargate_profile(
                    clusterName=cluster_name,
                    fargateProfileName=fp_name
                )
            
            # Wait for Fargate profiles to start deleting
            print("    Waiting for Fargate profiles to begin deletion...")
            time.sleep(20)
            
            return True
            
        except ClientError as e:
            print(f"    {Colors.RED}Error deleting Fargate profiles: {e}{Colors.END}")
            return False
    
    def delete_addons(self, cluster_name: str, addons: List[Dict[str, Any]], region: str) -> bool:
        """Delete all add-ons in a cluster"""
        if not addons:
            return True
        
        try:
            eks = self.session.client('eks', region_name=region)
            
            print(f"    Deleting {len(addons)} add-ons...")
            for addon in addons:
                addon_name = addon['addonName']
                print(f"      Deleting add-on {addon_name}")
                eks.delete_addon(
                    clusterName=cluster_name,
                    addonName=addon_name
                )
            
            # Add-ons delete relatively quickly
            time.sleep(10)
            
            return True
            
        except ClientError as e:
            print(f"    {Colors.RED}Error deleting add-ons: {e}{Colors.END}")
            return False
    
    def delete_cluster(self, cluster: Dict[str, Any], dry_run: bool = False) -> bool:
        """Delete an EKS cluster"""
        cluster_name = cluster['name']
        region = cluster['region']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete cluster {cluster_name} and all its resources{Colors.END}")
            return True
        
        try:
            eks = self.session.client('eks', region_name=region)
            
            # Delete add-ons first
            if cluster['addons']:
                if not self.delete_addons(cluster_name, cluster['addons'], region):
                    return False
            
            # Delete Fargate profiles
            if cluster['fargate_profiles']:
                if not self.delete_fargate_profiles(cluster_name, cluster['fargate_profiles'], region):
                    return False
            
            # Delete node groups
            if cluster['node_groups']:
                if not self.delete_node_groups(cluster_name, cluster['node_groups'], region):
                    return False
            
            # Wait longer for resources to finish deleting
            if cluster['node_groups'] or cluster['fargate_profiles']:
                print(f"    Waiting for cluster resources to finish deleting...")
                time.sleep(60)  # EKS resources take time to delete
            
            # Finally delete the cluster
            print(f"    Deleting cluster {cluster_name}...")
            eks.delete_cluster(name=cluster_name)
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                print(f"  {Colors.YELLOW}Cluster {cluster_name} not found (already deleted?){Colors.END}")
                return True
            elif error_code == 'ResourceInUseException':
                print(f"  {Colors.RED}Cluster {cluster_name} still has resources that need to be deleted{Colors.END}")
                return False
            else:
                print(f"  {Colors.RED}Error deleting {cluster_name}: {e}{Colors.END}")
                return False
    
    def delete_clusters(self, clusters: List[Dict[str, Any]], selected_cluster_names: List[str], dry_run: bool = False):
        """Delete selected clusters"""
        clusters_to_delete = [cluster for cluster in clusters if cluster['name'] in selected_cluster_names]
        
        if not clusters_to_delete:
            print(f"{Colors.YELLOW}No clusters selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*80}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING EKS CLUSTERS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS WILL DELETE ALL WORKLOADS AND DATA IN THE CLUSTERS!{Colors.END}")
            print(f"{Colors.RED}THIS ACTION CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*80}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, cluster in enumerate(clusters_to_delete, 1):
            cluster_name = cluster['name']
            region = cluster['region']
            monthly_cost = cluster['total_monthly_cost']
            
            node_count = sum(ng.get('scalingConfig', {}).get('desiredSize', 0) for ng in cluster['node_groups'])
            
            print(f"\n[{i}/{len(clusters_to_delete)}] Processing cluster: {cluster_name}")
            print(f"  Region: {region}, Nodes: {node_count}, Cost: ${monthly_cost:.2f}/month")
            print(f"  Node groups: {len(cluster['node_groups'])}, Fargate profiles: {len(cluster['fargate_profiles'])}")
            
            # Show warnings
            if cluster['safety']['warnings']:
                for warning in cluster['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_cluster(cluster, dry_run):
                success_text = "Would delete" if dry_run else "Successfully started deletion of"
                print(f"  {Colors.GREEN}✓ {success_text} {cluster_name}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {cluster_name}{Colors.END}")
                failed_count += 1
            
            # Longer delay for EKS operations
            if not dry_run:
                time.sleep(10)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deletion started"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} clusters{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} clusters{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            print(f"\n{Colors.RED}Warning: All workloads and data in the deleted clusters are permanently lost!{Colors.END}")
            print(f"{Colors.YELLOW}Note: EKS cluster deletion may take 10-15 minutes to complete.{Colors.END}")
            print(f"{Colors.BLUE}You can monitor deletion progress in the AWS Console.{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS EKS Cluster Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all clusters
        clusters = self.list_all_clusters()
        
        if not clusters:
            print(f"\n{Colors.GREEN}No EKS clusters found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(cluster['total_monthly_cost'] for cluster in clusters)
        risky_count = sum(1 for cluster in clusters if cluster['safety']['is_risky'])
        inactive_count = sum(1 for cluster in clusters if not cluster['activity'].get('has_recent_activity', False))
        empty_count = sum(1 for cluster in clusters if len(cluster['node_groups']) == 0)
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total clusters: {Colors.BLUE}{len(clusters)}{Colors.END}")
        print(f"Clusters with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive clusters: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Empty clusters (no node groups): {Colors.YELLOW}{empty_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  EKS deletion will destroy all workloads and data!{Colors.END}")
            print(f"{Colors.RED}⚠️  This action CANNOT be undone!{Colors.END}")
        
        # Ask what user wants to do
        proceed_msg = "Do you want to proceed with cluster selection?" if not dry_run else "Do you want to see what would be deleted?"
        if not self.get_user_confirmation(proceed_msg):
            return
        
        # Let user select clusters
        selected_cluster_names = self.show_cluster_selection_menu(clusters)
        
        if not selected_cluster_names:
            print(f"{Colors.BLUE}No clusters selected. Exiting.{Colors.END}")
            return
        
        selected_clusters = [cluster for cluster in clusters if cluster['name'] in selected_cluster_names]
        selected_cost = sum(cluster['total_monthly_cost'] for cluster in selected_clusters)
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected clusters: {Colors.YELLOW}{len(selected_clusters)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these clusters and ALL THEIR WORKLOADS?"
        if self.get_user_confirmation(final_question):
            self.delete_clusters(clusters, selected_cluster_names, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS EKS Cluster Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 eks_cleanup.py                          # Use default AWS profile
  python3 eks_cleanup.py --profile dev            # Use specific profile
  python3 eks_cleanup.py --dry-run                # Test mode - no actual deletions
  
Features:
  - Lists all EKS clusters with detailed cost analysis
  - Shows node groups, Fargate profiles, and add-ons
  - Identifies inactive clusters with no recent API activity
  - Safety warnings for clusters with active workloads
  - Very high cost impact: $72/month per cluster + worker node costs
  - Automatically deletes node groups and Fargate profiles first
  
Warning:
  EKS deletion permanently destroys all workloads and data and cannot be undone!
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
        cleaner = EKSCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()