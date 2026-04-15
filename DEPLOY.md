# Deploying Resy Bot to a Remote Server

## What you need

- A small Linux VPS (1 CPU / 1GB RAM is plenty)
  - ~$4-6/mo from DigitalOcean, Hetzner, Linode, etc.
- SSH access to the server
- Docker + Docker Compose installed on the server

## Setup

1. SSH into your server:
   ```
   ssh user@your-server-ip
   ```

2. Install Docker and Docker Compose:
   ```
   curl -fsSL https://get.docker.com | sh
   ```

3. Copy the project to the server:
   ```
   git clone <your-repo-url>
   ```
   Or from your laptop:
   ```
   rsync -avz --exclude '.git' . user@your-server-ip:~/jk-resy-bot/
   ```

4. Put your config files in place under `config_files/`.

5. Start the app (detached):
   ```
   docker compose up --build -d
   ```

The `restart: unless-stopped` policy in `docker-compose.yml` means the containers will survive server reboots.

## Updating

```
ssh user@your-server-ip
cd jk-resy-bot
git pull   # or rsync again from your laptop
docker compose up --build -d
```

## Viewing logs

The web UI is available at `http://your-server-ip:8995`.

**Important:** The web UI has no authentication. To keep it private, either:

- **SSH tunnel** (simplest): Access logs through an SSH tunnel without exposing the port publicly.
  ```
  ssh -L 8995:localhost:8995 user@your-server-ip
  ```
  Then open `http://localhost:8995` on your laptop.

- **Firewall**: Block port 8995 from public access using `ufw` or your VPS provider's firewall settings.

## Things to keep in mind

- **Config updates**: If you use Notion/Dropbox for remote config, it works the same as locally. If local-only, edit files directly on the server.
- **Logs persistence**: Docker logs survive container restarts, but `docker compose down` clears them. Add a Docker logging driver or volume mount if you want persistent history.
