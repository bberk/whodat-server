# Deploy to Oracle Cloud Always Free

Runbook for the production deployment: one Oracle Cloud Always Free ARM VM running the Compose
stack in `deploy/`. This is the supported hosting target. Local development still uses the root
`docker-compose.yml` (see the README).

## Topology

| Service | Image / build | Published ports | Notes |
|---|---|---|---|
| `caddy` | `caddy:2.10-alpine` | `80`, `443`, `443/udp` | Only ingress. Automatic Let's Encrypt TLS, `/api/*` and `/health` to the backend, everything else to the SPA. |
| `frontend` | `frontend/Dockerfile` | none | nginx on `8080`, serving the Vite build. `VITE_API_BASE_URL=https://$DOMAIN` is baked in at build time. |
| `backend` | `backend/Dockerfile` | none | Runs `alembic upgrade head`, then uvicorn on `8000`. |
| `postgres` | `postgres:18` | none | Named volume `pgdata`; reachable only on the Compose network. |

One origin (`https://$DOMAIN`) serves both the SPA and the API. That is what keeps the
`SameSite=Lax` session cookie first-party; no `SameSite=None` or wildcard CORS is needed.
`ENV=production` also makes the cookie `Secure` and makes the backend refuse its default secret.

## 1. Create the VM

In the Oracle Cloud console: **Compute → Instances → Create instance**.

- **Image:** Ubuntu 24.04 (aarch64).
- **Shape:** Ampere `VM.Standard.A1.Flex`, 2 OCPU / 12 GB (or 1 OCPU / 6 GB if capacity is tight).
  This fits inside the Always Free A1 allowance.
- **Boot volume:** 50–100 GB (Always Free includes 200 GB of block storage).
- **Networking:** assign a public IPv4 address; keep the default VCN.
- **SSH key:** upload your public key.

ARM capacity errors ("out of host capacity") are common at signup. Retry, try another availability
domain, or start with 1 OCPU / 6 GB and resize later.

Oracle may require a payment method for identity verification. Always Free resources stay free;
the card can see a temporary authorization **[unverified]**. Check the current console flow.

Do not run anything else on this VM: the Caddy container binds 80/443, and the stack assumes it is
the only user of those ports.

## 2. Open only 22, 80, and 443

On your laptop, record the operator IP that may SSH in:

```bash
curl -4 ifconfig.me
```

In the VCN's **security list** (or NSG), add ingress rules:

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | `<operator-ip>/32` **and** GitHub Actions ranges | SSH admin and the CI deploy (see below) |
| 80 | TCP | `0.0.0.0/0` | ACME HTTP challenge and HTTPS redirect |
| 443 | TCP | `0.0.0.0/0` | HTTPS |
| 443 | UDP | `0.0.0.0/0` | HTTP/3 (optional; TCP 443 is enough) |

Do **not** open 8000, 8080, or 5432. Those services have no published ports and must stay private.

The automatic deploy runs on a GitHub-hosted runner, whose IP is not yours. A 22 rule limited to
`<operator-ip>/32` alone makes the deploy hang and fail with `Connection timed out`. Pick one:

- **Add GitHub's `actions` ranges** to the 22 rule. List them with
  `curl -s https://api.github.com/meta | jq -r '.actions[]'` and refresh the rules when GitHub
  changes them (the list is large, so prefer an NSG or the OCI CLI over hand-editing many rules).
- **Run the deploy job on a self-hosted runner** in a network the 22 rule already allows; change
  `runs-on: ubuntu-latest` in `deploy.yml` to your runner label.
- **Open 22 to `0.0.0.0/0`** as a last resort, with key-only authentication and a brute-force
  blocker such as fail2ban. This is the weakest option.

Whichever you choose, keep SSH password authentication disabled and only the deploy key
authorized. The key material is only in the `production` environment secret.

Oracle's Ubuntu images also ship host firewall rules that reject most inbound traffic. On the VM:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
sudo iptables -L INPUT --line-numbers   # confirm 22, 80, 443 are accepted before the reject
```

If you lock yourself out of SSH, use the console's serial/VNC connection to fix the rules.

## 3. Install Docker and the Compose plugin

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
docker compose version
```

Docker builds ARM64 images on the VM; the first build takes several minutes on 2 OCPU.

## 4. Create the deploy user and checkout

```bash
sudo adduser --disabled-password --gecos "" whodat
sudo usermod -aG docker whodat
sudo install -d -m 755 -o whodat -g whodat /opt/whodat
sudo -u whodat git clone https://github.com/bberk/whodat-server.git /opt/whodat
```

The Docker group is effectively root-equivalent. Use a dedicated SSH key for deploys and keep the
`whodat` account limited to this host (no sudo).

Create the key on your laptop, then install its public half for `whodat`:

```bash
ssh-keygen -t ed25519 -C github-actions-deploy -f ~/.ssh/whodat_deploy
```

On the VM, as the default sudo user (`ubuntu`):

```bash
sudo install -d -m 700 -o whodat -g whodat /home/whodat/.ssh
sudo install -m 600 -o whodat -g whodat /dev/null /home/whodat/.ssh/authorized_keys
```

From your laptop:

```bash
cat ~/.ssh/whodat_deploy.pub | ssh ubuntu@<VM_IP> \
  'sudo tee -a /home/whodat/.ssh/authorized_keys >/dev/null'
ssh -i ~/.ssh/whodat_deploy whodat@<VM_IP> 'cd /opt/whodat && git log --oneline -1'
```

`deploy/deploy.sh` hard-resets this checkout to the commit being deployed. Do not edit files in
`/opt/whodat` by hand; put changes in the repository.

## 5. Create `deploy/.env`

```bash
sudo -iu whodat
cd /opt/whodat
umask 077
cp deploy/.env.example deploy/.env

DOMAIN=standings.example.com
DB_USER=whodat
DB_NAME=whodat
DB_PASSWORD="$(openssl rand -hex 32)"
SECRET_KEY="$(openssl rand -hex 32)"
LEAGUE_CREDENTIALS_KEY="$(openssl rand -base64 32)"

sed -i "s#^DOMAIN=.*#DOMAIN=$DOMAIN#" deploy/.env
sed -i "s#^CORS_ORIGINS=.*#CORS_ORIGINS=https://$DOMAIN#" deploy/.env
sed -i "s#^POSTGRES_USER=.*#POSTGRES_USER=$DB_USER#" deploy/.env
sed -i "s#^POSTGRES_DB=.*#POSTGRES_DB=$DB_NAME#" deploy/.env
sed -i "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=$DB_PASSWORD#" deploy/.env
sed -i "s#^SECRET_KEY=.*#SECRET_KEY=$SECRET_KEY#" deploy/.env
sed -i "s#^LEAGUE_CREDENTIALS_KEY=.*#LEAGUE_CREDENTIALS_KEY=$LEAGUE_CREDENTIALS_KEY#" deploy/.env
chmod 600 deploy/.env

# Confirm the keys exist without printing their values.
grep -v '^#' deploy/.env | cut -d= -f1
```

The production stack never falls back to the local-dev `app`/`app` credentials: `POSTGRES_USER`,
`POSTGRES_PASSWORD`, and `POSTGRES_DB` are required. `deploy/docker-compose.prod.yml` builds the
backend's `DATABASE_URL` from those same values as
`postgresql+psycopg://<user>:<password>@postgres:5432/<db>`, so the host, port, database, and
password cannot drift. Because of that, the password must stay hex (`openssl rand -hex 32`);
characters that need URL-encoding would break the URL.

Never echo, paste, or commit the values. `deploy/.env` is git-ignored. If you change `DOMAIN`,
update `CORS_ORIGINS` in the same file and redeploy so the frontend is rebuilt with the new origin.
Changing `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start does not
alter an existing `pgdata` volume: create a fresh volume for a new identity, or change the role
and database manually before redeploying.

## 6. Point DNS at the VM

Create an `A` record for the hostname (`standings.example.com` → the VM's public IPv4). Add an
`AAAA` record only if the instance has public IPv6.

```bash
dig +short standings.example.com
```

While testing before DNS is available, use a wildcard DNS service that maps an IP into a hostname.
With the VM's public IPv4, this gives you a working name and certificate:

```bash
VM_IP=140.238.1.2
DOMAIN="${VM_IP//./-}.sslip.io"   # 140-238-1-2.sslip.io
dig +short "$DOMAIN"              # should print the VM IP
```

`nip.io` works the same way. Caddy can obtain a certificate for those names, so you get
end-to-end TLS without owning a domain. Use the same value for `DOMAIN` and
`CORS_ORIGINS=https://<name>` in `deploy/.env`.

Caddy needs public port 80 (HTTP-01) and 443 (TLS-ALPN) to issue the certificate. A wrong DNS
record or a closed port 80 is the usual reason the first deploy fails its health check.

## 7. First manual deploy

```bash
sudo -iu whodat
cd /opt/whodat
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.prod.yml ps
curl -fsS "https://standings.example.com/health"   # {"status":"ok"}
```

If the health check fails, read Caddy's logs first:

```bash
docker compose -f deploy/docker-compose.prod.yml logs --tail=100 caddy
docker compose -f deploy/docker-compose.prod.yml logs --tail=100 backend
```

## 8. Create the first admin invite

There is no self-service signup; every account redeems an invite.

```bash
sudo -iu whodat
cd /opt/whodat
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec backend uv run python -m app.cli create-invite --role admin
```

The raw code is printed once and cannot be shown again. Sign up at
`https://standings.example.com/signup`, then create the league with its ESPN id, season, and
`ESPN_S2`/`ESPN_SWID` cookies. Member invites are created with `--role member --league <espn-id>`.

## 9. Configure the GitHub `production` environment

In **Settings → Environments**, create `production` (optionally add required reviewers; that
pauses each deploy until someone approves it).

Secrets (never echoed by the workflow):

| Name | Value |
|---|---|
| `SSH_HOST` | VM public IP or hostname. |
| `SSH_USER` | `whodat`. |
| `SSH_KEY` | The private key for the deploy user, for example `~/.ssh/whodat_deploy`. |
| `SSH_KNOWN_HOSTS` | The VM's host public keys, so SSH verifies the host instead of trusting it blindly. |

Variables (not secrets):

| Name | Value |
|---|---|
| `DEPLOY_PATH` | `/opt/whodat`. |
| `DOMAIN` | The public hostname, for example `standings.example.com`. |

The workflow needs no database, `SECRET_KEY`, or `LEAGUE_CREDENTIALS_KEY` values: migrations and
the app environment live on the VM in `deploy/.env`.

Generate `SSH_KNOWN_HOSTS` with the same host string you use for `SSH_HOST`, and check the
fingerprint against the VM's `/etc/ssh/ssh_host_ed25519_key.pub`:

```bash
SSH_HOST="<VM_IP_or_hostname>"   # the same value you will store in the secret
ssh-keyscan -H "$SSH_HOST" > known_hosts
ssh-keygen -lf known_hosts
```

With `gh`:

```bash
gh secret set SSH_HOST --env production --body "<VM_IP_or_hostname>"
gh secret set SSH_USER --env production --body whodat
gh secret set SSH_KEY --env production < ~/.ssh/whodat_deploy
gh secret set SSH_KNOWN_HOSTS --env production < known_hosts
gh variable set DEPLOY_PATH --env production --body /opt/whodat
gh variable set DOMAIN --env production --body standings.example.com
```

The workflow fails with a named, non-secret error if any of these is missing or malformed.

## 10. How the CI-gated deploy works

`.github/workflows/deploy.yml` runs after the **`ci`** workflow completes successfully for a push
to `main` (`workflow_run` with `branches: [main]`, `conclusion: success`). A pull request, a
failed CI run, or a cancelled run cannot reach the deploy job. `workflow_dispatch` is the manual
override and intentionally skips that gate.

The job:

1. checks out the exact `head_sha` CI validated;
2. verifies the `production` environment's secrets and variables;
3. copies `deploy/deploy.sh` to `/tmp` on the VM over SCP;
4. runs it over SSH as `whodat` with the SHA.

`deploy/deploy.sh` fetches and hard-resets `/opt/whodat` to that SHA, rebuilds both images with
`--pull`, runs `docker compose up -d`, and waits for `https://$DOMAIN/health` (falling back to the
backend container over local HTTP while DNS/TLS is still propagating). On any failure it resets to
the previously deployed SHA, rebuilds, and restarts. The previous SHA is also written to
`~/.local/state/whodat-deploy/previous-sha` on the VM.

Deploys are serialized by `concurrency: deploy-production` with `cancel-in-progress: false`, so a
second merge queues instead of interrupting a rollout. Only `actions/checkout` and the runner's
OpenSSH client are used.

## 11. Rollback

Automatic: a failed deploy restores the previous SHA before the workflow fails.

Manual, on the VM:

```bash
sudo -iu whodat
cd /opt/whodat
cat ~/.local/state/whodat-deploy/previous-sha
bash deploy/deploy.sh <full-40-character-sha>
```

Pick any earlier commit with `git log --oneline -10`. Deploying an older commit is a normal
rollback; the database schema is not reverted, so prefer a roll-forward fix if a migration is
involved.

## 12. Nightly backups and restore

Install the systemd unit and timer:

```bash
sudo install -d -m 700 -o whodat -g whodat /var/backups/whodat
sudo cp /opt/whodat/deploy/systemd/whodat-backup.service \
  /opt/whodat/deploy/systemd/whodat-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now whodat-backup.timer

# Run one now and check the result.
sudo systemctl start whodat-backup.service
sudo journalctl -u whodat-backup.service -n 50 --no-pager
sudo systemctl list-timers whodat-backup.timer
```

The timer runs daily at 03:15 UTC (`Persistent=true` catches up after downtime). The script writes
`/var/backups/whodat/whodat-<timestamp>.sql.gz` with mode 0600 in a 0700 directory and deletes
dumps older than 14 days. Override the retention or destination with
`sudo systemctl edit whodat-backup.service` and, for example,
`Environment=BACKUP_RETENTION_DAYS=30` or `Environment=BACKUP_DIR=/srv/backups/whodat`.

These dumps sit on the same VM, so they cover accidental deletion and bad migrations, not losing
the instance or its disk. Copy them off-box (`scp`, or Oracle Object Storage) for disaster
recovery.

Restore (stop writers first; the dump uses `--clean --if-exists`):

```bash
sudo -iu whodat
cd /opt/whodat
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env stop backend
gunzip -c /var/backups/whodat/whodat-<timestamp>.sql.gz |
  docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
    exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env start backend
curl -fsS "https://standings.example.com/health"
```

Rehearse a restore into a scratch database before you need it:

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" restore_test'
gunzip -c /var/backups/whodat/whodat-<timestamp>.sql.gz |
  docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
    exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d restore_test'
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env \
  exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" restore_test'
```

## 13. Caveats and maintenance

- **Single node, no HA.** One VM hosts the database, API, and SPA. A reboot, host failure, or
  kernel update means downtime; there is no failover.
- **Idle-instance reclamation.** Oracle may reclaim Always Free instances that stay below 20%
  CPU/network/memory for seven days. Create a free external monitor (UptimeRobot, Healthchecks.io,
  or similar) for `https://$DOMAIN/health` with a 5-minute interval; treat any 2xx as healthy and
  alert to your email. The probe is external infrastructure, not app telemetry, and needs no code
  change. A monitor alone does not guarantee the instance is kept, but it removes long idle gaps
  and tells you immediately if Oracle or the host takes it away.
- **ARM capacity at signup.** "Out of host capacity" is common for A1.Flex. Retry, switch
  availability domain, or use 1 OCPU / 6 GB. Upgrading the account to pay-as-you-go is reported to
  improve capacity **[unverified]**.
- **Card verification.** Oracle may ask for a payment method during signup; Always Free resources
  remain free within the published limits. Confirm the current terms in the console.
- **Patch the VM.** Enable `unattended-upgrades`, apply `apt-get update && apt-get upgrade`
  monthly, and reboot during a quiet window. `deploy/deploy.sh` runs `docker compose build
  --pull`, so base images pick up patches on the next deploy; rebuild after a Docker engine update.
- **Secrets live only in `deploy/.env`.** It is 0600, git-ignored, and mounted into Compose by
  reference. `docker compose config` would print it, so do not paste that output anywhere.
  Rotating `SECRET_KEY` signs everyone out; rotating `LEAGUE_CREDENTIALS_KEY` makes stored ESPN
  credentials unreadable until members re-enter them.
- **Docker group is root-equivalent.** The `whodat` account can control Docker; keep its SSH key
  only in the `production` environment secret.
- **Certs and data live in volumes.** `docker compose down` keeps `pgdata`, `caddy_data`, and
  `caddy_config`; `docker compose down --volumes` destroys them. Never run the latter in
  production.
- **No registry.** Images are built on the VM. A slow deploy is a build, not a rollback loop.
- **One origin only.** If you ever split the SPA and API across sites, the `SameSite=Lax` cookie
  stops being sent; that is a code and security change, not a deployment tweak.
- **Rate limiting is in-process.** Run one backend container, as this stack does. Do not scale
  the backend out behind Caddy without moving the limiter to a shared store.
