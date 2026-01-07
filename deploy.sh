#!/bin/bash

# SiteTesterPro Deployment Script
# Usage: ./deploy.sh

echo "=========================================="
echo "    SiteTesterPro Deployment Script       "
echo "=========================================="

# 1. Update System Packages
echo "[1/7] Updating system packages..."
sudo apt-get update && sudo apt-get install -y python3-venv python3-pip libpq-dev

# 2. Set up Python Environment
echo "[2/7] Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
fi

# Activate venv
source venv/bin/activate

# 3. Install Python Dependencies
echo "[3/7] Installing dependencies..."
# Upgrade pip first
pip install --upgrade pip
# Install requirements
pip install -r requirements.txt

# 4. Install Playwright Browsers
echo "[4/7] Installing Playwright browsers..."
playwright install chromium
playwright install-deps chromium

# 5. Create Database Directory
echo "[5/7] Setting up directories..."
mkdir -p database screenshots videos diffs temp_frames

# 6. Environment Setup Check
if [ ! -f ".env" ]; then
    echo "WARNING: .env file not found!"
    echo "Creating a template .env file..."
    cat > .env << EOL
# Database
DATABASE_URL=sqlite:///./database/database.db


# Security
SECRET_KEY=$(openssl rand -hex 32)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
EOL
    echo "Please edit .env with your actual configuration."
fi

# 8. Firewall Setup (UFW)
echo "[8/8] Configuring firewall..."
if command -v ufw > /dev/null; then
    ufw allow 8004/tcp
    echo "Port 8004 allowed."
else
    echo "UFW not found. Please ensure port 8004 is open in your firewall."
fi

# 9. Create Start Script
echo "[9/9] Creating start script (start.sh)..."
cat > start.sh << EOL
#!/bin/bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8004 --workers 4
EOL
chmod +x start.sh

# 8. Create Systemd Service File (Optional suggestion)
echo "[7/7] generating systemd service file (sitetester.service)..."
cat > sitetester.service << EOL
[Unit]
Description=SiteTesterPro Service
After=network.target

[Service]
User=root
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/start.sh
Restart=always

[Install]
WantedBy=multi-user.target
EOL

echo "=========================================="
echo "Deployment Setup Complete!"
echo "To run manually: ./start.sh"
echo "To install as service: copy sitetester.service to /etc/systemd/system/ and enable it."
echo "Don't forget to configure your .env file!"
echo "=========================================="
