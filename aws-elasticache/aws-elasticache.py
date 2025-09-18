#!/usr/bin/env python3
"""
AWS ElastiCache Cleanup Tool
Lists all ElastiCache clusters (Redis and Memcached) and allows safe deletion with cost analysis.
ElastiCache instances can cost $20-200+ per month, making cleanup valuable.
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

class ElastiCacheCleaner:
    def __init__(self, profile_name: str = None):
        """Initialize the AWS ElastiCache cleaner"""
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
                elasticache = self.session.client('elasticache', region_name=region)
                elasticache.describe_cache_clusters(MaxRecords=1)
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
    
    def get_elasticache_pricing(self, node_type: str, engine: str, region: str) -> float:
        """Get rough monthly pricing for ElastiCache node"""
        # Simplified pricing estimates (actual pricing varies by region and reserved instances)
        
        base_pricing = {
            # Cache nodes - General Purpose
            'cache.t3.micro': 0.017,     # $0.017/hour = ~$12.24/month
            'cache.t3.small': 0.034,     # $0.034/hour = ~$24.48/month
            'cache.t3.medium': 0.068,    # $0.068/hour = ~$48.96/month
            'cache.t2.micro': 0.017,
            'cache.t2.small': 0.034,
            'cache.t2.medium': 0.068,
            
            # Memory Optimized
            'cache.r5.large': 0.188,     # $0.188/hour = ~$135.36/month
            'cache.r5.xlarge': 0.375,    # $0.375/hour = ~$270/month
            'cache.r5.2xlarge': 0.75,    # $0.75/hour = ~$540/month
            'cache.r5.4xlarge': 1.5,     # $1.5/hour = ~$1080/month
            'cache.r4.large': 0.156,
            'cache.r4.xlarge': 0.311,
            'cache.r4.2xlarge': 0.622,
            
            # Compute Optimized
            'cache.c5.large': 0.096,     # $0.096/hour = ~$69.12/month
            'cache.c5.xlarge': 0.192,    # $0.192/hour = ~$138.24/month
            'cache.c5.2xlarge': 0.384,   # $0.384/hour = ~$276.48/month
            
            # Previous generation
            'cache.m5.large': 0.113,
            'cache.m5.xlarge': 0.226,
            'cache.m4.large': 0.111,
            'cache.m4.xlarge': 0.221,
        }
        
        # Redis costs slightly more than Memcached
        engine_multiplier = 1.1 if engine.lower() == 'redis' else 1.0
        
        # Some regions are more expensive
        expensive_regions = ['ap-south-1', 'ap-southeast-1', 'sa-east-1']
        region_multiplier = 1.2 if region in expensive_regions else 1.0
        
        # Get base hourly cost
        hourly_cost = base_pricing.get(node_type, 0.05)  # Default to $0.05/hour if unknown
        
        # Calculate monthly cost (24 hours * 30 days)
        monthly_cost = hourly_cost * 24 * 30 * engine_multiplier * region_multiplier
        
        return monthly_cost
    
    def get_cache_metrics(self, cluster_id: str, engine: str, region: str) -> Dict[str, Any]:
        """Get CloudWatch metrics for ElastiCache cluster"""
        try:
            cloudwatch = self.session.client('cloudwatch', region_name=region)
            
            # Get metrics for the last 30 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=30)
            
            # Different metrics for Redis vs Memcached
            if engine.lower() == 'redis':
                # Redis metrics
                connections_response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/ElastiCache',
                    MetricName='CurrConnections',
                    Dimensions=[{'Name': 'CacheClusterId', 'Value': cluster_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Average', 'Maximum']
                )
                
                hits_response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/ElastiCache',
                    MetricName='CacheHits',
                    Dimensions=[{'Name': 'CacheClusterId', 'Value': cluster_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Sum']
                )
                
                misses_response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/ElastiCache',
                    MetricName='CacheMisses',
                    Dimensions=[{'Name': 'CacheClusterId', 'Value': cluster_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Sum']
                )
            else:
                # Memcached metrics
                connections_response = cloudwatch.get_metric_statistics(
                    Namespace='AWS/ElastiCache',
                    MetricName='CurrConnections',
                    Dimensions=[{'Name': 'CacheClusterId', 'Value': cluster_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,
                    Statistics=['Average', 'Maximum']
                )
                
                hits_response = {'Datapoints': []}
                misses_response = {'Datapoints': []}
            
            # Process connections
            avg_connections = 0
            max_connections = 0
            if connections_response['Datapoints']:
                avg_connections = sum(point['Average'] for point in connections_response['Datapoints']) / len(connections_response['Datapoints'])
                max_connections = max(point['Maximum'] for point in connections_response['Datapoints'])
            
            # Process cache hits/misses
            total_hits = sum(point['Sum'] for point in hits_response['Datapoints'])
            total_misses = sum(point['Sum'] for point in misses_response['Datapoints'])
            
            return {
                'avg_connections': avg_connections,
                'max_connections': max_connections,
                'total_hits': total_hits,
                'total_misses': total_misses,
                'has_activity': avg_connections > 0 or total_hits > 0
            }
            
        except ClientError as e:
            return {
                'error': str(e),
                'avg_connections': 0,
                'max_connections': 0,
                'total_hits': 0,
                'total_misses': 0,
                'has_activity': False
            }
    
    def check_cache_safety(self, cache_info: Dict[str, Any]) -> Dict[str, Any]:
        """Check if cache cluster appears to be important or in use"""
        cluster_id = cache_info['cluster_id']
        safety_warnings = []
        
        # Check for important patterns in name
        important_patterns = [
            'prod', 'production', 'live', 'main', 'primary',
            'critical', 'session', 'web', 'api'
        ]
        
        cluster_lower = cluster_id.lower()
        for pattern in important_patterns:
            if pattern in cluster_lower:
                safety_warnings.append(f"Name contains '{pattern}' - might be important")
        
        # Check if cluster has recent activity
        metrics = cache_info['metrics']
        if metrics['has_activity']:
            if metrics['avg_connections'] > 1:
                safety_warnings.append(f"Active cluster: {metrics['avg_connections']:.1f} avg connections")
            if metrics['total_hits'] > 1000:
                safety_warnings.append(f"Cache activity: {metrics['total_hits']:,} hits in 30 days")
        
        # Check if cluster is in a VPC (more likely to be important)
        if cache_info.get('vpc_id'):
            safety_warnings.append("Cluster in VPC")
        
        # Check if cluster has encryption (more likely to be important)
        if cache_info.get('at_rest_encryption_enabled'):
            safety_warnings.append("Encryption at rest enabled")
        
        if cache_info.get('transit_encryption_enabled'):
            safety_warnings.append("Encryption in transit enabled")
        
        # Check if cluster has automatic backups (Redis only)
        if cache_info.get('snapshot_retention_limit', 0) > 0:
            safety_warnings.append(f"Automatic backups enabled ({cache_info['snapshot_retention_limit']} days)")
        
        # Check if recently created (within 7 days)
        created_time = cache_info['created_time']
        days_since_created = (datetime.now(timezone.utc) - created_time).days
        if days_since_created <= 7:
            safety_warnings.append(f"Recently created ({days_since_created} days ago)")
        
        return {
            'is_risky': len(safety_warnings) > 0,
            'warnings': safety_warnings,
            'days_since_created': days_since_created
        }
    
    def list_cache_clusters_in_region(self, region: str) -> List[Dict[str, Any]]:
        """List all ElastiCache clusters in a specific region"""
        try:
            elasticache = self.session.client('elasticache', region_name=region)
            
            clusters = []
            
            # Get cache clusters (both Redis and Memcached)
            paginator = elasticache.get_paginator('describe_cache_clusters')
            
            for page in paginator.paginate(ShowCacheNodeInfo=True):
                for cluster in page['CacheClusters']:
                    cluster_id = cluster['CacheClusterId']
                    engine = cluster['Engine']
                    
                    # Skip clusters that are part of replication groups (handled separately)
                    if cluster.get('ReplicationGroupId'):
                        continue
                    
                    # Get metrics
                    metrics = self.get_cache_metrics(cluster_id, engine, region)
                    
                    # Get pricing
                    monthly_cost = self.get_elasticache_pricing(
                        cluster['CacheNodeType'],
                        engine,
                        region
                    )
                    
                    # Multiply by number of nodes
                    num_cache_nodes = cluster['NumCacheNodes']
                    total_monthly_cost = monthly_cost * num_cache_nodes
                    
                    cluster_info = {
                        'cluster_id': cluster_id,
                        'region': region,
                        'engine': engine,
                        'engine_version': cluster['EngineVersion'],
                        'node_type': cluster['CacheNodeType'],
                        'status': cluster['CacheClusterStatus'],
                        'num_cache_nodes': num_cache_nodes,
                        'created_time': cluster['CacheClusterCreateTime'],
                        'availability_zone': cluster.get('PreferredAvailabilityZone', 'Multiple'),
                        'vpc_id': cluster.get('CacheSubnetGroupName'),  # Indicates VPC
                        'security_groups': [sg['SecurityGroupId'] for sg in cluster.get('SecurityGroups', [])],
                        'parameter_group': cluster.get('CacheParameterGroup', {}).get('CacheParameterGroupName', ''),
                        'snapshot_retention_limit': cluster.get('SnapshotRetentionLimit', 0),
                        'at_rest_encryption_enabled': cluster.get('AtRestEncryptionEnabled', False),
                        'transit_encryption_enabled': cluster.get('TransitEncryptionEnabled', False),
                        'metrics': metrics,
                        'monthly_cost': total_monthly_cost,
                        'cluster_type': 'standalone'
                    }
                    
                    # Add safety check
                    cluster_info['safety'] = self.check_cache_safety(cluster_info)
                    
                    clusters.append(cluster_info)
            
            # Get Redis replication groups (Redis clusters with read replicas)
            try:
                rep_groups_paginator = elasticache.get_paginator('describe_replication_groups')
                
                for page in rep_groups_paginator.paginate():
                    for rep_group in page['ReplicationGroups']:
                        rep_group_id = rep_group['ReplicationGroupId']
                        
                        # Get total cost (sum of all member clusters)
                        total_cost = 0
                        total_nodes = 0
                        node_type = 'Unknown'
                        
                        for member_cluster in rep_group.get('MemberClusters', []):
                            try:
                                cluster_response = elasticache.describe_cache_clusters(
                                    CacheClusterId=member_cluster,
                                    ShowCacheNodeInfo=True
                                )
                                member = cluster_response['CacheClusters'][0]
                                node_cost = self.get_elasticache_pricing(
                                    member['CacheNodeType'],
                                    'redis',
                                    region
                                )
                                total_cost += node_cost * member['NumCacheNodes']
                                total_nodes += member['NumCacheNodes']
                                node_type = member['CacheNodeType']
                            except ClientError:
                                pass
                        
                        # Get metrics for the primary cluster
                        primary_cluster = rep_group.get('MemberClusters', [None])[0]
                        metrics = {'has_activity': False, 'avg_connections': 0}
                        if primary_cluster:
                            metrics = self.get_cache_metrics(primary_cluster, 'redis', region)
                        
                        rep_group_info = {
                            'cluster_id': rep_group_id,
                            'region': region,
                            'engine': 'redis',
                            'engine_version': rep_group.get('CacheNodeType', 'Unknown'),
                            'node_type': node_type,
                            'status': rep_group['Status'],
                            'num_cache_nodes': total_nodes,
                            'created_time': rep_group.get('ReplicationGroupCreateTime', datetime.now(timezone.utc)),
                            'availability_zone': 'Multiple',
                            'vpc_id': rep_group.get('CacheSubnetGroupName'),
                            'security_groups': [],
                            'parameter_group': '',
                            'snapshot_retention_limit': rep_group.get('SnapshotRetentionLimit', 0),
                            'at_rest_encryption_enabled': rep_group.get('AtRestEncryptionEnabled', False),
                            'transit_encryption_enabled': rep_group.get('TransitEncryptionEnabled', False),
                            'metrics': metrics,
                            'monthly_cost': total_cost,
                            'cluster_type': 'replication_group',
                            'member_clusters': rep_group.get('MemberClusters', [])
                        }
                        
                        # Add safety check
                        rep_group_info['safety'] = self.check_cache_safety(rep_group_info)
                        
                        clusters.append(rep_group_info)
                        
            except ClientError:
                # Replication groups might not be available in all regions
                pass
            
            return clusters
            
        except ClientError as e:
            print(f"{Colors.RED}Error listing ElastiCache clusters in {region}: {e}{Colors.END}")
            return []
    
    def format_cluster_info(self, cluster: Dict[str, Any]) -> str:
        """Format cluster information for display"""
        cluster_id = cluster['cluster_id'][:20] if len(cluster['cluster_id']) > 20 else cluster['cluster_id']
        region = cluster['region']
        engine = cluster['engine'].upper()
        node_type = cluster['node_type'][:15]
        status = cluster['status'][:10]
        
        num_nodes = cluster['num_cache_nodes']
        monthly_cost = cluster['monthly_cost']
        cluster_type = 'RG' if cluster['cluster_type'] == 'replication_group' else 'SA'
        
        # Activity indicator
        metrics = cluster['metrics']
        if metrics.get('has_activity'):
            activity = f"{metrics['avg_connections']:.0f} conn"
        else:
            activity = "No activity"
        
        created_time = cluster['created_time']
        days_ago = (datetime.now(timezone.utc) - created_time).days
        
        # Encryption indicator
        encryption = "✓" if cluster.get('at_rest_encryption_enabled') or cluster.get('transit_encryption_enabled') else "✗"
        
        # Safety indicator
        if cluster['safety']['is_risky']:
            safety_indicator = f"{Colors.RED}⚠{Colors.END}"
        else:
            safety_indicator = f"{Colors.GREEN}✓{Colors.END}"
        
        return f"  {cluster_id:<20} | {region:<12} | {engine:<8} | {node_type:<15} | {status:<10} | {cluster_type:<2} | {num_nodes:>2} | {activity:<12} | {encryption:<3} | ${monthly_cost:>6.0f} | {days_ago:>3}d | {safety_indicator}"
    
    def list_all_clusters(self) -> List[Dict[str, Any]]:
        """List all ElastiCache clusters across accessible regions"""
        print(f"\n{Colors.BLUE}{'='*150}{Colors.END}")
        print(f"{Colors.BLUE}Scanning ElastiCache Clusters across regions...{Colors.END}")
        print(f"{Colors.BLUE}{'='*150}{Colors.END}")
        
        all_clusters = []
        total_cost = 0
        
        for region in self.accessible_regions:
            print(f"\n{Colors.YELLOW}Checking region: {region}{Colors.END}")
            
            clusters = self.list_cache_clusters_in_region(region)
            
            if clusters:
                region_cost = sum(cluster['monthly_cost'] for cluster in clusters)
                region_nodes = sum(cluster['num_cache_nodes'] for cluster in clusters)
                
                redis_count = sum(1 for c in clusters if c['engine'].lower() == 'redis')
                memcached_count = sum(1 for c in clusters if c['engine'].lower() == 'memcached')
                
                print(f"{Colors.GREEN}Found {len(clusters)} clusters{Colors.END}")
                print(f"  Redis: {redis_count}, Memcached: {memcached_count}")
                print(f"  Total nodes: {region_nodes}")
                print(f"  Estimated monthly cost: ${region_cost:.2f}")
                
                total_cost += region_cost
                all_clusters.extend(clusters)
            else:
                print(f"{Colors.GREEN}No clusters found{Colors.END}")
        
        # Display summary
        risky_count = sum(1 for cluster in all_clusters if cluster['safety']['is_risky'])
        inactive_count = sum(1 for cluster in all_clusters if not cluster['metrics'].get('has_activity', False))
        
        # Count by engine
        redis_clusters = [c for c in all_clusters if c['engine'].lower() == 'redis']
        memcached_clusters = [c for c in all_clusters if c['engine'].lower() == 'memcached']
        
        print(f"\n{Colors.BOLD}ELASTICACHE CLUSTERS SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*150}{Colors.END}")
        
        # Get current account info
        sts = self.session.client('sts')
        account_info = sts.get_caller_identity()
        
        print(f"AWS Account ID: {Colors.YELLOW}{account_info['Account']}{Colors.END}")
        print(f"Total clusters found: {Colors.YELLOW}{len(all_clusters)}{Colors.END}")
        print(f"  Redis clusters: {Colors.BLUE}{len(redis_clusters)}{Colors.END}")
        print(f"  Memcached clusters: {Colors.BLUE}{len(memcached_clusters)}{Colors.END}")
        print(f"Clusters with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive clusters: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Total estimated annual cost: {Colors.YELLOW}${total_cost * 12:.2f}{Colors.END}")
        print(f"Regions scanned: {Colors.YELLOW}{', '.join(self.accessible_regions)}{Colors.END}")
        
        if all_clusters:
            print(f"\n{Colors.BOLD}CLUSTER DETAILS{Colors.END}")
            print(f"{Colors.BLUE}{'='*150}{Colors.END}")
            print(f"  {'Cluster ID':<20} | {'Region':<12} | {'Engine':<8} | {'Node Type':<15} | {'Status':<10} | {'Type':<2} | {'Nodes':<2} | {'Activity':<12} | {'Enc':<3} | {'Cost':<7} | {'Age':<4} | Safe")
            print(f"  {'-'*20} | {'-'*12} | {'-'*8} | {'-'*15} | {'-'*10} | {'-'*2} | {'-'*2} | {'-'*12} | {'-'*3} | {'-'*7} | {'-'*4} | {'-'*4}")
            
            # Sort by cost (highest first)
            sorted_clusters = sorted(all_clusters, key=lambda x: -x['monthly_cost'])
            
            for cluster in sorted_clusters:
                print(self.format_cluster_info(cluster))
                
                # Show safety warnings
                if cluster['safety']['warnings']:
                    for warning in cluster['safety']['warnings'][:2]:
                        print(f"    {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            # Show breakdown by engine
            print(f"\n{Colors.BOLD}BREAKDOWN BY ENGINE{Colors.END}")
            if redis_clusters:
                redis_cost = sum(c['monthly_cost'] for c in redis_clusters)
                print(f"  Redis        : {len(redis_clusters)} clusters, ${redis_cost:.2f}/month")
            if memcached_clusters:
                memcached_cost = sum(c['monthly_cost'] for c in memcached_clusters)
                print(f"  Memcached    : {len(memcached_clusters)} clusters, ${memcached_cost:.2f}/month")
        
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
        print("Or enter 'memcached' to select only Memcached clusters")
        print("Or enter 'safe' to select only clusters without warnings")
        print("")
        
        # Show numbered list
        inactive_clusters = []
        safe_clusters = []
        memcached_clusters = []
        
        for i, cluster in enumerate(clusters, 1):
            safety_indicator = f"{Colors.RED}⚠{Colors.END}" if cluster['safety']['is_risky'] else f"{Colors.GREEN}✓{Colors.END}"
            monthly_cost = cluster['monthly_cost']
            engine = cluster['engine'].upper()
            
            activity_indicator = ""
            if not cluster['metrics'].get('has_activity', False):
                activity_indicator = f"{Colors.YELLOW}(INACTIVE){Colors.END}"
                inactive_clusters.append(cluster['cluster_id'])
            
            if not cluster['safety']['is_risky']:
                safe_clusters.append(cluster['cluster_id'])
            
            if cluster['engine'].lower() == 'memcached':
                memcached_clusters.append(cluster['cluster_id'])
            
            print(f"{i:2d}. {cluster['cluster_id']:<25} | {cluster['region']:<12} | {engine:<8} | ${monthly_cost:>6.0f}/mo | {safety_indicator} {activity_indicator}")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Your selection: {Colors.END}").strip().lower()
            
            if choice == 'all':
                return [cluster['cluster_id'] for cluster in clusters]
            elif choice == 'inactive':
                if inactive_clusters:
                    return inactive_clusters
                else:
                    print(f"{Colors.RED}No inactive clusters found{Colors.END}")
                    continue
            elif choice == 'memcached':
                if memcached_clusters:
                    return memcached_clusters
                else:
                    print(f"{Colors.RED}No Memcached clusters found{Colors.END}")
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
                            selected.append(clusters[idx-1]['cluster_id'])
                        else:
                            print(f"{Colors.RED}Invalid cluster number: {idx}{Colors.END}")
                            raise ValueError()
                    
                    return selected
                    
                except ValueError:
                    print(f"{Colors.RED}Invalid input. Please enter numbers separated by commas, 'all', 'inactive', 'memcached', or 'safe'{Colors.END}")
    
    def delete_cluster(self, cluster: Dict[str, Any], dry_run: bool = False) -> bool:
        """Delete a single ElastiCache cluster"""
        cluster_id = cluster['cluster_id']
        region = cluster['region']
        cluster_type = cluster['cluster_type']
        
        if dry_run:
            print(f"  {Colors.BLUE}[DRY RUN] Would delete cluster {cluster_id}{Colors.END}")
            return True
        
        try:
            elasticache = self.session.client('elasticache', region_name=region)
            
            if cluster_type == 'replication_group':
                # Delete Redis replication group
                elasticache.delete_replication_group(
                    ReplicationGroupId=cluster_id,
                    RetainPrimaryCluster=False
                )
            else:
                # Delete standalone cluster
                elasticache.delete_cache_cluster(CacheClusterId=cluster_id)
            
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['CacheClusterNotFound', 'ReplicationGroupNotFoundFault']:
                print(f"  {Colors.YELLOW}Cluster {cluster_id} already deleted{Colors.END}")
                return True
            else:
                print(f"  {Colors.RED}Error deleting {cluster_id}: {e}{Colors.END}")
                return False
    
    def delete_clusters(self, clusters: List[Dict[str, Any]], selected_cluster_names: List[str], dry_run: bool = False):
        """Delete selected clusters"""
        clusters_to_delete = [cluster for cluster in clusters if cluster['cluster_id'] in selected_cluster_names]
        
        if not clusters_to_delete:
            print(f"{Colors.YELLOW}No clusters selected for deletion.{Colors.END}")
            return
        
        mode_text = "DRY RUN - " if dry_run else ""
        print(f"\n{Colors.RED}{'='*70}{Colors.END}")
        print(f"{Colors.RED}{mode_text}DELETING ELASTICACHE CLUSTERS{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}THIS CANNOT BE UNDONE!{Colors.END}")
        print(f"{Colors.RED}{'='*70}{Colors.END}")
        
        deleted_count = 0
        failed_count = 0
        total_savings = 0
        
        for i, cluster in enumerate(clusters_to_delete, 1):
            cluster_id = cluster['cluster_id']
            region = cluster['region']
            engine = cluster['engine']
            monthly_cost = cluster['monthly_cost']
            num_nodes = cluster['num_cache_nodes']
            
            print(f"\n[{i}/{len(clusters_to_delete)}] Processing cluster: {cluster_id}")
            print(f"  Engine: {engine}, Nodes: {num_nodes}, Region: {region}, Cost: ${monthly_cost:.2f}/month")
            
            # Show warnings
            if cluster['safety']['warnings']:
                for warning in cluster['safety']['warnings'][:3]:
                    print(f"  {Colors.YELLOW}⚠ {warning}{Colors.END}")
            
            if self.delete_cluster(cluster, dry_run):
                success_text = "Would delete" if dry_run else "Successfully deleted"
                print(f"  {Colors.GREEN}✓ {success_text} {cluster_id}{Colors.END}")
                deleted_count += 1
                total_savings += monthly_cost
            else:
                print(f"  {Colors.RED}✗ Failed to delete {cluster_id}{Colors.END}")
                failed_count += 1
            
            # Small delay to avoid rate limiting
            if not dry_run:
                time.sleep(2)
        
        # Final summary
        print(f"\n{Colors.BOLD}{'DRY RUN ' if dry_run else ''}DELETION SUMMARY{Colors.END}")
        print(f"{Colors.BLUE}{'='*50}{Colors.END}")
        success_text = "would be deleted" if dry_run else "deleted"
        print(f"Successfully {success_text}: {Colors.GREEN}{deleted_count} clusters{Colors.END}")
        print(f"Failed: {Colors.RED}{failed_count} clusters{Colors.END}")
        print(f"Estimated monthly savings: {Colors.GREEN}${total_savings:.2f}{Colors.END}")
        print(f"Estimated annual savings: {Colors.GREEN}${total_savings * 12:.2f}{Colors.END}")
        
        if not dry_run and deleted_count > 0:
            print(f"\n{Colors.YELLOW}Note: Cluster deletion may take 5-10 minutes to complete.{Colors.END}")
    
    def run(self, dry_run: bool = False):
        """Main execution flow"""
        mode_text = " (DRY RUN MODE)" if dry_run else ""
        print(f"{Colors.BOLD}AWS ElastiCache Cleanup Tool{mode_text}{Colors.END}")
        print(f"{Colors.BLUE}{'='*70}{Colors.END}")
        
        if dry_run:
            print(f"{Colors.BLUE}Running in DRY RUN mode - no actual deletions will be performed{Colors.END}")
        
        # Test region connectivity
        accessible_regions = self.test_region_connectivity()
        print(f"\n{Colors.GREEN}Accessible regions: {', '.join(accessible_regions)}{Colors.END}")
        
        # List all clusters
        clusters = self.list_all_clusters()
        
        if not clusters:
            print(f"\n{Colors.GREEN}No ElastiCache clusters found! Nothing to delete.{Colors.END}")
            return
        
        # Show deletion options
        total_cost = sum(cluster['monthly_cost'] for cluster in clusters)
        risky_count = sum(1 for cluster in clusters if cluster['safety']['is_risky'])
        inactive_count = sum(1 for cluster in clusters if not cluster['metrics'].get('has_activity', False))
        
        print(f"\n{Colors.YELLOW}⚠️  DELETION OPTIONS{Colors.END}")
        print(f"{Colors.YELLOW}{'='*50}{Colors.END}")
        print(f"Total clusters: {Colors.BLUE}{len(clusters)}{Colors.END}")
        print(f"Clusters with warnings: {Colors.RED}{risky_count}{Colors.END}")
        print(f"Inactive clusters: {Colors.YELLOW}{inactive_count}{Colors.END}")
        print(f"Total estimated monthly cost: {Colors.YELLOW}${total_cost:.2f}{Colors.END}")
        print(f"Potential annual savings: {Colors.GREEN}${total_cost * 12:.2f}{Colors.END}")
        if not dry_run:
            print(f"{Colors.RED}⚠️  Deletion will permanently remove selected clusters!{Colors.END}")
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
        
        selected_clusters = [cluster for cluster in clusters if cluster['cluster_id'] in selected_cluster_names]
        selected_cost = sum(cluster['monthly_cost'] for cluster in selected_clusters)
        
        # Final confirmation
        confirmation_text = "DRY RUN CONFIRMATION" if dry_run else "FINAL CONFIRMATION"
        print(f"\n{Colors.RED}{confirmation_text}{Colors.END}")
        print(f"Selected clusters: {Colors.YELLOW}{len(selected_clusters)}{Colors.END}")
        print(f"Monthly savings: {Colors.GREEN}${selected_cost:.2f}{Colors.END}")
        print(f"Annual savings: {Colors.GREEN}${selected_cost * 12:.2f}{Colors.END}")
        
        final_question = "Proceed with analysis?" if dry_run else "Are you absolutely sure you want to delete these clusters?"
        if self.get_user_confirmation(final_question):
            self.delete_clusters(clusters, selected_cluster_names, dry_run)
        else:
            print(f"{Colors.BLUE}Operation cancelled by user.{Colors.END}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AWS ElastiCache Cleanup Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 elasticache_cleanup.py                  # Use default AWS profile
  python3 elasticache_cleanup.py --profile dev    # Use specific profile
  python3 elasticache_cleanup.py --dry-run        # Test mode - no actual deletions
  
Features:
  - Lists all ElastiCache clusters (Redis and Memcached) with cost estimates
  - Shows activity metrics and connection statistics
  - Identifies inactive clusters with no recent usage
  - Handles both standalone clusters and Redis replication groups
  - Cost impact: clusters typically cost $20-200+ per month
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
        cleaner = ElastiCacheCleaner(profile_name=args.profile)
        cleaner.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user (Ctrl+C){Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        sys.exit(1)

if __name__ == '__main__':
    main()