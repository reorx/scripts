---
name: systools
description: System operations toolkit for local development and debugging. Use when the user needs to kill a process on a port, find what's using a port, free up a port, or deal with "address already in use" errors. Also use for any system-level task like checking listening ports or managing local processes — even if they just say "something is using port 3000" or "kill whatever is on port 8080".
---

# systools

A collection of tools and best practices for common system operations during local development and debugging.

## Port Management

### Kill process on a port

**Script:** `scripts/portkill.sh`

Use this when a user needs to free up a port — e.g., "address already in use", "port 3000 is taken", or "kill whatever is on port 8080".

**How to use:**

```bash
bash <skill-path>/scripts/portkill.sh <port>
```

The script will:
1. Look up all processes listening on the given TCP port via `lsof`
2. Display the process details (PID, command, user)
3. Prompt for confirmation before killing

**Important:** This script is interactive (prompts y/N). When running it for the user, either:
- Run it directly so the user sees the prompt and can confirm, OR
- If the user has already confirmed they want to kill the process, pipe `y` into it: `echo y | bash <skill-path>/scripts/portkill.sh <port>`

**When NOT to use this script:**
- If the user just wants to *check* what's on a port without killing, use `lsof -i tcp:<port> -P -n` directly instead.
