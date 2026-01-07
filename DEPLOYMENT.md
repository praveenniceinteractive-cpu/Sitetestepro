# Deployment Instructions

## 1. Prerequisites
- A Linux server (Ubuntu 20.04/22.04 recommended)
- Root (SSH) access
- Python 3.10+ installed

## 2. FTP Upload
Upload the entire `sitetoolpro` data folder to your server (e.g., to `/root/sitetoolpro` or `/var/www/sitetoolpro`).
**Exclude** the following local folders to save time (they will be recreated):
- `venv/`
- `__pycache__/`
- `screenshots/`
- `videos/`
- `temp_frames/`

## 3. SSH Setup
Connect to your server via SSH:
```bash
ssh root@your-server-ip
cd /path/to/sitetoolpro
```

## 4. Run Deployment Script
I have verified the code and created an automated script to handle installation.
Make the script executable and run it:

```bash
chmod +x deploy.sh
./deploy.sh
```

This script will:
1. Update system packages.
2. Create a Python virtual environment.
3. Install all dependencies from `requirements.txt`.
4. Install Playwright browsers and system dependencies.
5. Create necessary directories.
6. Generate a strictly secure `.env` file if one doesn't exist.

## 5. Configure Environment
Edit the generated `.env` file with your specific settings:
```bash
nano .env
```
Ensure your `SECRET_KEY` is set to a secure random string.

## 6. Run the Application
You can start the server using the generated start script:

```bash
./start.sh
```
The application will be live at `http://your-server-ip:8004`.

## 7. Production Service (Optional)
To keep the app running in the background after you disconnect:

1. Copy the service file:
   ```bash
   cp sitetester.service /etc/systemd/system/
   ```
2. Reload systemd:
   ```bash
   systemctl daemon-reload
   ```
3. Start and enable the service:
   ```bash
   systemctl start sitetester
   systemctl enable sitetester
   ```
