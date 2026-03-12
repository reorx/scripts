---
name: flyctl
description: Use when deploying services to Fly.io, configuring fly.toml, managing Fly machines, or troubleshooting Fly deployments
---

# flyctl

Reference for deploying lightweight services to Fly.io using `flyctl`.

## Quick Reference

| Task | Command |
|------|---------|
| Create app | `fly apps create <app-name> --org personal` |
| Deploy | `fly deploy` |
| Status | `fly status -a <app-name>` |
| Logs | `fly logs -a <app-name>` |
| Set secret | `fly secrets set KEY=value -a <app-name>` |
| List secrets | `fly secrets list -a <app-name>` |
| Scale to 1 machine | `fly scale count 1 -a <app-name> --yes` |
| Show VM spec | `fly scale show -a <app-name>` |
| List VM sizes | `fly platform vm-sizes` |
| Destroy app | `fly apps destroy <app-name> --yes` |

## fly.toml Minimal Template

For lightweight services (Go proxies, static services, etc.):

```toml
app = 'app-name'
primary_region = 'nrt'

[build]
  image = 'username/image:latest'

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = 'stop'
  auto_start_machines = true
  min_machines_running = 0
  processes = ['app']

[[vm]]
  memory = '256mb'
  cpu_kind = 'shared'
  cpus = 1
```

## Key Patterns

### Single Machine Deployment

Default `fly deploy` creates 2 machines for HA. After deploy, run:

```bash
fly scale count 1 -a <app-name> --yes
```

### Skip Fly's Builder

Fly's depot builder can hang. Use pre-built Docker Hub images instead:

```toml
[build]
  image = 'username/image-name:latest'
```

This makes `fly deploy` pull only, no build.

### Secrets

Secrets set before first deploy show "staged for the first deployment" and take effect on deploy. They don't trigger a restart.

## VM Sizes

| Name | CPU | Memory |
|------|-----|--------|
| shared-cpu-1x | 1 | 256 MB |
| shared-cpu-2x | 2 | 512 MB |
| shared-cpu-4x | 4 | 1024 MB |
| performance-1x | 1 | 2048 MB |
| performance-2x | 2 | 4096 MB |
