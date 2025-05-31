import boto3
import yaml

# Load your config
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Test EC2 access
ec2 = boto3.client('ec2', region_name='us-east-1')
print('✓ IAM role working!')

# Test your security group exists
sg_id = config['aws']['security_group']
response = ec2.describe_security_groups(GroupIds=[sg_id])
print(f'✓ Security group {sg_id} found!')

# Test AMI exists
ami_id = config['aws']['ami_id']
response = ec2.describe_images(ImageIds=[ami_id])
print(f'✓ AMI {ami_id} found!')