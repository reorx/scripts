---
name: flyctl
description: Use when deploying services to Fly.io, configuring fly.toml, managing Fly machines, volumes, domains, health checks, or troubleshooting Fly deployments. Trigger this skill whenever the user mentions Fly.io, flyctl, fly deploy, fly.toml, or wants to run containers on Fly — even if they just say "deploy this to Fly" or "put this on fly.io".
---

# flyctl

Reference for deploying services to Fly.io using `flyctl`.

## Quick Reference

| Task | Command |
|------|---------|
| Create app | `fly apps create <app-name> --org personal` |
| Deploy | `fly deploy` |
| Status | `fly status -a <app-name>` |
| Logs | `fly logs -a <app-name>` |
| SSH into machine | `fly ssh console -a <app-name>` |
| Download file from machine | `fly ssh sftp get -a <app-name> /remote/path local-path` |
| Set secret | `fly secrets set KEY=value -a <app-name>` |
| List secrets | `fly secrets list -a <app-name>` |
| Suspend app (stop all) | `fly scale count 0 -a <app-name>` |
| Resume app | `fly scale count 1 -a <app-name> --yes` |
| Change VM size | `fly scale vm shared-cpu-1x -a <app-name>` |
| Show VM spec | `fly scale show -a <app-name>` |
| List VM sizes | `fly platform vm-sizes` |
| Create volume | `fly volumes create <name> --region nrt --size 1 -a <app-name>` |
| List volumes | `fly volumes list -a <app-name>` |
| Add certificate | `fly certs add <domain> -a <app-name>` |
| Check certificate | `fly certs show <domain> -a <app-name>` |
| Allocate IP | `fly ips allocate-v4 --shared -a <app-name>` |
| List IPs | `fly ips list -a <app-name>` |
| Destroy app | `fly apps destroy <app-name> --yes` |

## fly.toml Configuration Blocks

Compose a fly.toml by combining the blocks below. Every fly.toml starts with:

```toml
app = 'app-name'
primary_region = 'nrt'
```

### Build

Always use pre-built images. Never use `dockerfile = 'Dockerfile'` — Fly's depot builder is slow and unreliable. Build and push images externally (CI, GitHub Actions, etc.).

```toml
[build]
  image = 'ghcr.io/org/image:v1.0.0'
```

### HTTP Service

```toml
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = 'stop'
  auto_start_machines = true
  min_machines_running = 0
  processes = ['app']
```

### Always-On (no auto-stop)

For services that must stay running (e.g. SQLite-backed apps, stateful services). Pin to exactly one machine:

```toml
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1
  max_machines_running = 1
  processes = ['app']
```

### Volume Mount

For persistent storage (SQLite, file-based data). Create the volume before deploying: `fly volumes create <vol-name> --region <region> --size 1 -a <app-name>`

```toml
[[mounts]]
  source = 'data'
  destination = '/data'
```

### Environment Variables

```toml
[env]
  DB_PATH = '/data/app.db'
  HOST = '0.0.0.0'
  PORT = 5678
```

### Custom Entrypoint

Override the image's default command:

```toml
[experimental]
  cmd = ['server', 'start']
```

### VM Size

Get started with a small vm:

```toml
[[vm]]
  size = 'shared-cpu-1x'
```

## Key Patterns

### Single Machine / Always-On

Default `fly deploy` creates 2 machines for HA. To pin to exactly one machine that never stops, set in `[http_service]`:

```toml
min_machines_running = 1
max_machines_running = 1
```

Alternatively, scale down after deploy: `fly scale count 1 -a <app-name> --yes`

### Skip Fly's Builder

Fly's depot builder can hang. Use pre-built Docker Hub images instead:

```toml
[build]
  image = 'username/image-name:latest'
```

This makes `fly deploy` pull only, no build.

### Secrets

Secrets set before first deploy show "staged for the first deployment" and take effect on deploy. They don't trigger a restart.

After first deploy, setting a secret triggers an automatic redeploy.

### Custom Domains

```bash
# 1. Allocate a shared IPv4 (free) and get the IPv6
fly ips allocate-v4 --shared -a <app-name>
fly ips list -a <app-name>

# 2. Add DNS records at your registrar:
#    A record    → the IPv4 address
#    AAAA record → the IPv6 address

# 3. Add certificate (auto-provisions via Let's Encrypt)
fly certs add <domain> -a <app-name>

# 4. Check certificate status
fly certs show <domain> -a <app-name>
```

### Health Checks

Add to fly.toml to let Fly know when your app is ready:

```toml
[checks]
  [checks.health]
    type = 'http'
    port = 8080
    path = '/health'
    interval = '15s'
    timeout = '5s'
```

### Backup Volume Data

SSH in, tar the data, then pull it down:

```bash
fly ssh console -a <app-name>
# inside the machine:
tar czf /tmp/backup.tgz /data

# back on local machine:
fly ssh sftp get -a <app-name> /tmp/backup.tgz backup.tgz
```

### Upload Files to Volume

When you need to upload data (e.g. migrating to a smaller volume), you can temporarily swap the image to a utility image with curl, deploy, upload via a transfer service, then swap back:

```bash
# 1. Change fly.toml image to a utility image (e.g. one with curl)
# 2. fly deploy
# 3. fly ssh console -a <app-name>
#    curl <transfer-url> -o /data/backup.tgz && tar xzf /data/backup.tgz
# 4. Change fly.toml image back to the real app
# 5. fly deploy
```

### Cloudflare Proxy with Fly

When using Cloudflare proxy (orange cloud) in front of a Fly app:
- Set Cloudflare SSL mode to **Full** — otherwise requests loop or fail
- Fly certificates still work behind CF proxy
- Use CF Transform Rules to rewrite URL paths if you need to disguise endpoints (e.g. rewrite `/goat` to `/count` to avoid adblockers)

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Deploy hangs on builder | Use pre-built image instead of Dockerfile build |
| Machine stuck in `replacing` | `fly machines list -a <app>`, then `fly machines destroy <id> --force` |
| App not reachable | Check `fly ips list` — need at least one IP allocated |
| Certificate pending | DNS not propagated yet; check with `fly certs check <domain>` |
| Out of memory | Increase VM: `fly scale vm shared-cpu-2x -a <app>` or set `size = 'shared-cpu-2x'` in fly.toml |
| Volume not mounting | Volume must be in same region as machine; check with `fly volumes list` |
| App keeps stopping unexpectedly | Set `auto_stop_machines = false` and `min_machines_running = 1` for always-on |
