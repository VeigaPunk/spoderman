# spoderman-droplet

## Specs
- **Provider:** DigitalOcean
- **Region:** NYC3
- **Size:** s-2vcpu-4gb-120gb-intel (2 vCPU / 4GB RAM / 120GB NVMe / Intel Shared)
- **OS:** Ubuntu 24.04 LTS
- **Cost:** $32/month
- **IP:** 165.227.178.152
- **Droplet ID:** 576702018

## SSH Access

```
ssh root@165.227.178.152
```

Auth: SSH key only (password auth disabled). Use `hermes-key`.

### Termius Setup
1. Open Termius → **New Host**
2. **Hostname:** `165.227.178.152`
3. **Port:** `22`
4. **Username:** `root`
5. **Auth:** Keychain → import your `hermes-key` private key
6. Save and connect

## What's Installed (via cloud-init)
- UFW firewall (22, 80, 443 open)
- fail2ban (SSH brute-force protection)
- 2GB swapfile (`/swapfile`)
- curl, wget, git, htop, vim, unzip, net-tools
- SSH hardened: password auth off, root key-only

## Firewall Rules
| Port | Protocol | Purpose |
|------|----------|---------|
| 22   | TCP      | SSH     |
| 80   | TCP      | HTTP    |
| 443  | TCP      | HTTPS   |
