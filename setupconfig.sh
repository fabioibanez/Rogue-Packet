# Make sure we're working in us-east-1
export AWS_DEFAULT_REGION=us-east-1

# Create security group in us-east-1
SG_ID=$(aws ec2 create-security-group \
    --region us-east-1 \
    --group-name bittorrent-test-sg-useast1 \
    --description "Security group for BitTorrent testing in us-east-1" \
    --query 'GroupId' \
    --output text)

echo "Created security group in us-east-1: $SG_ID"

# Add the required rules
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id $SG_ID --protocol tcp --port 6881-6999 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0

echo "✓ Security group rules added"

# Get Ubuntu AMI for us-east-1
AMI_ID=$(aws ec2 describe-images --region us-east-1 --owners 099720109477 --filters 'Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*' --query 'Images[0].ImageId' --output text)

echo "✓ Ubuntu AMI ID for us-east-1: $AMI_ID"

echo ""
echo "=== Your config.yaml for us-east-1 ==="
cat << EOF
aws:
  instance_type: "t2.micro"
  security_group: "$SG_ID"
  ami_id: "$AMI_ID"

controller:
  port: 8080

bittorrent:
  github_repo: "https://github.com/fabioibanez/Rogue-Packet.git"
  torrent_url: "https://raw.githubusercontent.com/fabioibanez/Rogue-Packet/main/test.torrent"

regions:
  - name: "us-east-1"
    seeders: 1
    leechers: 2

timeout_minutes: 30
EOF
