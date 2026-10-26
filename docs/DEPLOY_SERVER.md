# Generic-server deployment runbook

This runbook deploys the app to one generic Linux server and manages it manually from a macOS or
Linux laptop. The laptop uses an SSH Docker context; there is no GitHub Actions deploy workflow,
registry, Kubernetes cluster, or cloud-provider dependency.

## 1. Topology and limits

The Compose project contains:

- **Caddy**, the only ingress, publishing TCP 80 (optional HTTP redirect) and TCP 443 (HTTPS).
- **Frontend**, nginx serving the built SPA on the private Compose network.
- **Backend**, one process that runs `alembic upgrade head` and then starts uvicorn.
- **Postgres**, with its data directory on a named volume.

Caddy serves one origin, `https://<subdomain>.duckdns.org`. It sends `/api/*` and `/health` to the
backend and every other request to the frontend. The frontend nginx image supplies the SPA
`index.html` fallback. The browser therefore uses the same origin for the SPA, API, and session
cookie, whose attributes include `Secure`, `HttpOnly`, and `SameSite=Lax`.

Caddy gets and renews certificates with DuckDNS **DNS-01**. Inbound port 80 is not needed for
certificate issuance. The DuckDNS updater refreshes the public IPv4 record every five minutes
because the home/public address can rotate.

Only Caddy publishes host ports. Postgres, uvicorn, and nginx have no host-published ports. Never
publish or forward 22, 8000, 8080, or 5432 to the internet. SSH management is LAN-only (or through
a VPN that joins the laptop to that LAN).

**This is a single-node setup with no high availability, failover, or coordinated replicas.** The
server, its disk, the home router, and the ISP connection are single points of failure. Rate limits
are in-process, so keep one backend replica. The server must receive regular OS, Docker, and
application security patches. Keep an off-server backup; a named volume is not a backup.

## 2. Hardware and OS

Supported hosts:

- Debian 12 or 13, or Ubuntu 24.04, with current security updates.
- amd64 or arm64. The images and builds select the server's native architecture.
- Recommended starting size: 2 CPU cores, 4 GiB RAM, and 30 GiB free disk.
- Add disk for Postgres growth, Docker build cache, logs, and any backups kept on the server.

The remote daemon builds the backend and frontend, so a small server needs enough RAM for the Node
build. Do not run another copy of the root development Compose stack on the same ports.

## 3. Prepare the server

### 3.1 Create a non-root deploy user

Create a sudo-capable user for administration and Docker access:

```bash
sudo adduser deploy
sudo usermod -aG sudo deploy
```

On Debian, install `sudo` first if the minimal image does not include it. Docker installation below
adds this user to the `docker` group. Membership in that group is effectively root access because
it can mount the host filesystem into containers; protect the account accordingly.

### 3.2 Install SSH keys and disable password authentication

On the **laptop**, create a key if you do not already have one, then copy it to the server. Replace
the example LAN address throughout this runbook:

```bash
ssh-keygen -t ed25519 -a 64
ssh-copy-id deploy@192.168.1.50
ssh deploy@192.168.1.50
```

After the key login works, create `/etc/ssh/sshd_config.d/99-whodat-hardening.conf` on the server
with `sudoedit`:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

Validate and reload SSH. Keep the existing session open until a second key-based session succeeds:

```bash
sudo sshd -t
sudo systemctl reload ssh
```

### 3.3 Reserve the LAN address and check for CGNAT

Give the server a DHCP reservation in the router, or configure a static LAN address outside the
DHCP pool. A reservation is usually easier to audit. Record the address and verify it with:

```bash
ip -brief address
ip route
```

The DuckDNS record tracks the **public WAN** address; the Docker context uses the **stable LAN**
address. These are different settings.

Before forwarding ports, compare the router's WAN IPv4 address with the public address seen by the
server:

```bash
curl -4 https://api.ipify.org
printf '\n'
```

If the router WAN address is in 10/8, 172.16/12, 192.168/16, or 100.64/10, or differs because the
ISP supplies private addressing, the connection may be behind CGNAT or double NAT. Inbound
forwarding through this kit will not work through CGNAT. Ask the ISP for a public dynamic IPv4
address or remove the extra NAT layer. Do not expose SSH or substitute an unreviewed tunnel; a
tunnel-based topology is outside this runbook.

### 3.4 Configure the firewall and router

The example uses UFW and the LAN subnet `192.168.1.0/24`; replace that subnet with the real one.
Allow SSH before enabling the firewall so you do not lock yourself out:

```bash
sudo apt-get update
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp
sudo ufw enable
sudo ufw status verbose
```

Port 80 is optional and only redirects to HTTPS. Omit that rule if you do not want the redirect.
Docker can interact directly with firewall rules; this kit limits published ports to Caddy's 80
and 443. Re-audit `docker ps` and the firewall if other stacks run on the host.

In the router, forward **external TCP 443 to TCP 443 on the server's LAN address**. Optionally
forward TCP 80 the same way for redirects. Do not forward any other port, and do not enable a DMZ
for the server. Disable unneeded router UPnP port mappings. Test public access from a cellular or
other external network because some routers cannot hairpin their own public address.

### 3.5 Install Docker Engine and the compose plugin

These are the official Docker apt-repository steps for Debian and Ubuntu. Run them on the server:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
. /etc/os-release
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Do not add a `tcp://` daemon listener. The laptop reaches the existing Unix socket through SSH;
opening Docker's TCP API would create another ingress and a serious security risk.

Configure Docker log rotation. If `/etc/docker/daemon.json` already exists, merge these keys rather
than discarding unrelated settings:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Then restart Docker during this initial maintenance window and grant the deploy user access:

```bash
sudo systemctl restart docker
sudo usermod -aG docker deploy
sudo docker version
docker compose version
```

Log out and back in after changing group membership. The Compose file also sets 10 MiB, three-file
log limits for every service. Review journald retention separately if the host has strict disk
limits.

## 4. Configure DuckDNS and its server updater

1. Sign in at <https://www.duckdns.org/> and create one subdomain.
2. Set `DOMAIN` everywhere to the full hostname, such as `standings.duckdns.org`.
3. Copy the account token from the DuckDNS page. Treat it as a secret; it authorizes DNS changes.

The systemd updater runs on the server as the non-root `duckdns` user. It needs a copy of the three
files from `deploy/server/`; a checkout on the server is used only for these operational files and
optional server-side backups. The remote Docker build does not read that checkout.

From the repository checkout on the server, install the updater and units:

```bash
sudo groupadd --system duckdns
sudo useradd --system --gid duckdns --no-create-home \
  --shell /usr/sbin/nologin duckdns
sudo install -D -m 0755 deploy/server/duckdns-update.sh \
  /usr/local/libexec/whodat-duckdns-update
sudo install -m 0644 deploy/server/duckdns-update.service \
  /etc/systemd/system/duckdns-update.service
sudo install -m 0644 deploy/server/duckdns-update.timer \
  /etc/systemd/system/duckdns-update.timer
```

Create the token environment file without putting the token in shell history:

```bash
sudo install -d -m 0755 /etc/whodat
sudo install -m 0600 /dev/null /etc/whodat/duckdns.env
sudoedit /etc/whodat/duckdns.env
```

Use these keys with real values in the root-owned, mode-0600 file:

```text
DOMAIN=your-subdomain.duckdns.org
DUCKDNS_TOKEN=replace-with-the-real-token
```

Confirm the token file stays private before starting the service:

```bash
sudo chown root:root /etc/whodat/duckdns.env
sudo chmod 0600 /etc/whodat/duckdns.env
sudo stat -c '%a %U %G %n' /etc/whodat/duckdns.env
```

The expected output starts with `600 root root`. Start one immediate update, then enable the
five-minute timer:

```bash
sudo systemctl daemon-reload
sudo systemctl start duckdns-update.service
sudo systemctl enable --now duckdns-update.timer
systemctl status duckdns-update.service --no-pager
systemctl list-timers duckdns-update.timer --no-pager
```

The script sends an empty `ip=` over IPv4, so DuckDNS uses the server's detected public IPv4. It
passes the token to curl over stdin, not in process arguments, and logs neither the token nor the
response body. To inspect updates later:

```bash
journalctl -u duckdns-update.service --since today --no-pager
```

Verify the public record from the laptop or server:

```bash
dig +short A your-subdomain.duckdns.org
```

The result should be the current public IPv4, not the server's LAN address.

## 5. Prepare the laptop Docker context

Install a current Docker CLI with the compose plugin. Docker Desktop is the simplest macOS option;
on Linux, install the Docker CLI and compose plugin from your distribution or Docker's repository.
The SSH server and Docker daemon must already work as described above.

From the repository root on the laptop, either use the wrapper:

```bash
./deploy/server/manage.sh context-create deploy@192.168.1.50 whodat-server
```

or the equivalent Docker command:

```bash
docker context create whodat-server \
  --docker host=ssh://deploy@192.168.1.50
```

Select the context in each laptop shell used to manage the app, then check it:

```bash
export DOCKER_CONTEXT=whodat-server
./deploy/server/manage.sh check
```

`DOCKER_CONTEXT` is deliberately explicit. `manage.sh` refuses an unset context, an unknown
context, or any context whose endpoint is not `ssh://`; this prevents an accidental deployment to
the local daemon. Use `manage.sh contexts` to list the available names.

The remote model has important path consequences:

- The laptop CLI reads `docker-compose.yml`, `.env`, and build contexts, then sends build input to
  the remote daemon.
- Images, containers, named volumes, `/data`, `/config`, and `/var/lib/postgresql` all live on the
  server.
- No laptop directory is bind-mounted. Caddy's Dockerfile bakes in its Caddyfile for this reason.
- Backup and restore filenames are local to the machine running the script. Through `manage.sh`,
  that machine is the laptop, and SQL crosses the Docker SSH connection as a stream.

## 6. Configure application secrets

On the laptop, create the private environment file and restrict its permissions:

```bash
cp deploy/server/.env.example deploy/server/.env
chmod 600 deploy/server/.env
```

Edit `deploy/server/.env`; do not commit it. Generate independent values with:

```bash
openssl rand -hex 32     # SECRET_KEY
openssl rand -base64 32  # LEAGUE_CREDENTIALS_KEY
openssl rand -hex 24     # POSTGRES_PASSWORD
```

Set `DOMAIN`, `DUCKDNS_TOKEN`, both generated keys, and the three Postgres settings. Hex is used
for the database password so it needs no URL escaping. Keep these derived lines unchanged:

```text
DATABASE_URL=postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
CORS_ORIGINS=https://${DOMAIN}
ENV=production
```

The frontend build argument is also `https://${DOMAIN}`. Changing the domain later requires a
rebuild so the SPA gets the new API origin.

Refresh limits are optional. The production Compose defaults use a **5-second cooldown per league**
for both the league-wide refresh and the admin per-season refresh, with separate per-user buckets
(`REFRESH_LEAGUE_INTERVAL_SECONDS`, `REFRESH_USER_LIMIT`, `REFRESH_USER_WINDOW_SECONDS`,
`SEASON_REFRESH_LEAGUE_INTERVAL_SECONDS`, `SEASON_REFRESH_USER_LIMIT`,
`SEASON_REFRESH_USER_WINDOW_SECONDS`). This replaces the old five-minute league cooldown; after five
seconds another refresh of the same league is allowed. The league-wide per-user cap stays at three
per hour, while the per-season cap is 60 per hour. Override any value in `deploy/server/.env` and
restart the backend container. Keep `POSTGRES_USER` and `POSTGRES_DB` stable after the
first initialization. Changing `POSTGRES_PASSWORD` in `.env` does not change the role password in
an existing volume.

ESPN cookies are not deployment environment variables. Users enter them per membership in the UI,
and the backend encrypts them with `LEAGUE_CREDENTIALS_KEY`. Back up that key securely: losing it
makes stored league credentials unreadable. Rotating `SECRET_KEY` invalidates existing sessions.

## 7. First deployment

From the repository root on the laptop, with `DOCKER_CONTEXT` still selected:

```bash
./deploy/server/manage.sh deploy
```

This builds on the remote daemon, starts the four services, and waits for all healthchecks. The
backend command applies migrations before uvicorn starts. Caddy stores its ACME account and
certificates in named volumes; do not delete those volumes during routine operations.

Check the stack and logs if necessary:

```bash
./deploy/server/manage.sh ps
./deploy/server/manage.sh logs caddy
```

### 7.1 Create the first admin invite

Open a backend shell through the wrapper:

```bash
./deploy/server/manage.sh shell
```

Then run this inside the container:

```bash
uv run python -m app.cli create-invite --role admin
exit
```

The raw invite code is printed once and cannot be retrieved later. Save it temporarily in a secure
way, then redeem it at `https://your-subdomain.duckdns.org/signup`. The admin onboarding flow asks
for the ESPN league ID, season, `ESPN_S2`, and `ESPN_SWID`.

### 7.2 Verify health, HTTPS, routing, and cookies

Use the real domain in these commands:

```bash
curl --fail --show-error https://your-subdomain.duckdns.org/health
curl --fail --show-error --head https://your-subdomain.duckdns.org/login
curl --include https://your-subdomain.duckdns.org/api/v1/me
```

Expected results are `{"status":"ok"}`, the SPA page for `/login`, and a JSON 401 for `/api/v1/me`
when logged out. The last check proves API requests are not receiving the SPA fallback. If port 80
was forwarded, `curl --head http://your-subdomain.duckdns.org/` should return an HTTPS redirect.

After logging in through a browser, inspect the `whodat_session` cookie in its developer tools. It
must be host-only for the chosen domain with `Path=/`, `Secure`, `HttpOnly`, and `SameSite=Lax`.
Do not copy or log the cookie value. Also navigate directly to a client-side route and reload it
to verify the SPA fallback.

## 8. Routine laptop operations

All commands below require the selected remote context and the private `deploy/server/.env`:

| Command | Effect |
|---|---|
| `manage.sh check` | Refuse local contexts and verify the remote daemon over SSH. |
| `manage.sh deploy` | Build, start, and wait for every service to become healthy. |
| `manage.sh up` | Start/recreate from existing images without an explicit build. |
| `manage.sh down` | Remove containers/networks but preserve all named volumes. |
| `manage.sh logs [service ...]` | Follow all logs or only the named services. |
| `manage.sh ps` | Show current containers and health. |
| `manage.sh migrate` | Run `alembic upgrade head` in a one-off backend container. |
| `manage.sh shell [service]` | Open a shell; defaults to `backend`. |
| `manage.sh backup [directory]` | Write a compressed database dump on the laptop. |
| `manage.sh restore <file>` | Confirm, stop writers, restore, restart, and wait for health. |
| `manage.sh update` | Pull Postgres, rebuild with fresh base images, and start. |

Run them as `./deploy/server/manage.sh ...` from the repository root. `HEALTH_TIMEOUT` defaults to
300 seconds and can be set to a larger positive integer for a slow server.

`down` never passes `-v`. Do not manually run `docker compose down -v` unless you intentionally
want to destroy Postgres and Caddy's state and have verified a restorable backup elsewhere.

## 9. Backups and restore

### 9.1 Laptop backups

Choose or create a laptop directory outside the repository, then stream a backup to it:

```bash
./deploy/server/manage.sh backup "$HOME/Backups/whodat"
```

The command runs `pg_dump` inside the compose Postgres container with that container's actual
`POSTGRES_USER` and `POSTGRES_DB`. The password is not placed on a command line. Output is plain
SQL with clean/if-exists statements, compressed with gzip, named with a UTC timestamp, gzip-tested,
and finished with mode 0600. Each successful run deletes matching dumps in that directory that are
at least 14 days old. Without an argument, the destination is `./backups` in the current directory.

The dump contains password hashes, league data, and encrypted credentials, so treat it as sensitive
even though the credentials are encrypted. Keep an encrypted copy off the laptop and server. The
script does not encrypt backups itself.

For an optional server-side run, use a copy of `deploy/server/` on that server with the same `.env`
and project name, then call:

```bash
./backup.sh /path/to/restricted-backup-directory
```

It uses the server daemon directly and writes to the server's chosen directory. Do not confuse that
directory with the laptop destination used by `manage.sh backup`.

### 9.2 Restore

First confirm that `DOCKER_CONTEXT` names the intended server. Then run, replacing the filename:

```bash
./deploy/server/manage.sh restore \
  "$HOME/Backups/whodat/whodat-20261024T030000Z.sql.gz"
```

After a literal `yes` confirmation, the wrapper stops Caddy, frontend, and backend; waits for
Postgres; pipes the dump into `psql --single-transaction --set=ON_ERROR_STOP=1`; restarts the
stack; and waits for health. The backend applies any pending migrations on startup.

A failed SQL restore exits before restarting writers and leaves the app containers stopped. The
single transaction prevents a partial SQL restore. Inspect the error, fix the cause, then either
retry or use `manage.sh up` to return to the previous database state. Restoring an older backup
intentionally discards newer data, so make a fresh pre-restore backup when possible.

Test restores periodically on a separate, non-production Docker context. A backup that has never
been restored is not yet a verified recovery plan.

## 10. Upgrades and rollback

### 10.1 Normal upgrade

1. Schedule downtime; this single-node stack has no zero-downtime rollout.
2. Make a fresh laptop backup and copy it off the server.
3. Update the trusted deployment checkout on the laptop to the intended commit.
4. Review migration and release notes, then run:

   ```bash
   ./deploy/server/manage.sh update
   ./deploy/server/manage.sh ps
   curl --fail --show-error https://your-subdomain.duckdns.org/health
   ```

5. Check backend and Caddy logs, log in, and verify a standings read and an admin read.

`update` pulls the Postgres image, rebuilds the application and Caddy images with fresh base
images, and recreates containers as needed. The backend always runs migrations before uvicorn.
Use `manage.sh migrate` only when an explicit migration run is useful for diagnosis or a controlled
maintenance step.

### 10.2 Rollback

Record the known-good application commit before an upgrade. To roll back application code, switch
the laptop deployment checkout to that commit and run `manage.sh update` again. This rebuilds and
redeploys that source; it does not undo database migrations.

Database rollback is a separate restore decision. If the new schema is incompatible with the old
code, restore the pre-upgrade backup with `manage.sh restore`, accepting that data written after
that backup is lost. Do not run arbitrary `alembic downgrade` commands as a substitute for a tested
recovery plan. Restore the same trusted kit version before retrying.

## 11. Troubleshooting

### Certificate issuance fails

- Run `manage.sh logs caddy` and look for ACME or DuckDNS errors.
- Confirm `DOMAIN` is the full DuckDNS hostname and `DUCKDNS_TOKEN` matches that DuckDNS account.
- Check `dig +short A <domain>` and `dig TXT _acme-challenge.<domain>` against a public resolver.
  TXT records can take time to propagate; do not repeatedly delete Caddy's volumes or force a
  large number of issuance attempts against ACME rate limits.
- DNS-01 needs outbound HTTPS and DNS access, not inbound port 80. The DuckDNS plugin's default
  resolver is `8.8.8.8:53`; check whether the network blocks that resolver.
- Port 443 is still required for users to reach the completed HTTPS service.
- To validate the baked configuration without restarting the stack, use `manage.sh shell caddy`
  and run `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`.

### DuckDNS does not track the public IP

Check `systemctl status duckdns-update.timer` and `journalctl -u duckdns-update.service`. Confirm
that the root-owned `/etc/whodat/duckdns.env` is mode 0600 and has the same domain/token as the
Compose environment. Compare the record with `curl -4 https://api.ipify.org`. A `KO` result is
reported as a failed update without printing the token or response body.

### Public access fails despite correct DNS

Recheck CGNAT/double NAT, the router's 443 forwarding target, the server's LAN reservation, and
UFW. Test from outside the LAN to avoid hairpin-NAT false failures. If the ISP uses CGNAT, changing
Caddy or firewall settings cannot make this inbound topology reachable; obtain a public dynamic
IPv4 address from the ISP.

### Docker context errors

Run `manage.sh contexts`, confirm `DOCKER_CONTEXT` is spelled exactly, and inspect the chosen
context with `docker context inspect <name>`. Test `ssh deploy@192.168.1.50`, key-only auth, and
the deploy user's Docker group membership. The laptop must be on the allowed LAN or VPN because
port 22 is not internet-facing. `manage.sh` intentionally rejects `default`, Desktop, Unix-socket,
and TCP contexts even when they work.

### Postgres authentication or startup errors

- Inspect `manage.sh logs postgres` and `manage.sh logs backend`.
- Keep the derived `DATABASE_URL` references so user, password, database, and host stay aligned.
- After the first initialization, the Postgres image ignores changed `POSTGRES_*` values for the
  existing data directory. Do not fix this by deleting `postgres_data`.
- To change only the role password, first make a backup. Set the new value in `.env`, recreate the
  Postgres container, then open `manage.sh shell postgres` and run
  `psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"`. Use psql's interactive `\password`
  command so the new password is not placed in shell history. Recreate the backend afterwards.
- Changing the Postgres user or database name needs a deliberate migration/restore plan, not an
  environment-only edit.

### Backend stays unhealthy or the SPA uses an old domain

The backend does not become healthy until migrations finish and uvicorn answers `/health`; inspect
its logs before retrying. The frontend API origin is compiled at build time. After changing
`DOMAIN`, run `manage.sh deploy` or `manage.sh update`, not just `manage.sh up`, and hard-refresh
the browser.

## 12. Security and maintenance notes

- Patch the server regularly with `sudo apt-get update && sudo apt-get upgrade`; reboot when kernel
  or other updates require it. Docker restart policies and the DuckDNS timer resume after reboot,
  but verify `manage.sh ps` and `/health` afterwards.
- Keep SSH keys private, password authentication off, and port 22 restricted to the LAN/VPN.
- The Docker group is root-equivalent. Do not grant it to untrusted users or run unreviewed images.
- Keep `deploy/server/.env` mode 0600 and never commit it. `docker compose config` resolves and
  prints secrets, so do not paste its output into tickets or chat.
- Keep `/etc/whodat/duckdns.env` root-owned mode 0600. Rotate a leaked DuckDNS token immediately.
- Back up `LEAGUE_CREDENTIALS_KEY` separately and securely. Restrict and encrypt off-site database
  backups. Limit who can read Docker logs and shell history.
- Only 443 is required from the internet; 80 is an optional redirect. No application, database,
  SSH, or Docker API port belongs on the router's forwarding table.
- Revisit image pins and base-image updates during normal upgrades. Caddy and its DuckDNS plugin
  are version-pinned in `deploy/server/caddy/Dockerfile`.
- There is no HA or automatic disaster recovery. Document the latest known-good commit, test
  restores, and keep enough downtime budget for single-node maintenance.
