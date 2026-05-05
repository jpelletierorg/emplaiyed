# `calrs` Deployment Playbook

Deploy `calrs` on Fly.io at `meet.jpelletier.org`, using Spacemail as both the calendar source and outgoing mail provider, with Cloudflare managing DNS.

## Fixed values

- Public hostname: `meet.jpelletier.org`
- Fly region: `yyz`
- Recommended Fly app name: `jp-calrs`
- Recommended Fly volume name: `calrs_data`
- Spacemail mailbox: `moi@jpelletier.org`
- Spacemail CalDAV endpoint: `https://caldav.spacemail.com/`
- Spacemail IMAP/SMTP host: `mail.spacemail.com`
- Spacemail SMTP port: `465`

If `jp-calrs` is already taken on Fly, pick another unique app name. The custom hostname can stay the same.

## Secrets required

1. Fly login
2. Cloudflare login
3. Spacemail mailbox password for `moi@jpelletier.org`
4. The admin password you want to use for `calrs`

## Safety rules

1. Do not expose the app publicly until the admin account exists.
2. Keep open registration disabled permanently.
3. Do not scale to multiple Fly machines unless you add a SQLite replication strategy.
4. Start Cloudflare in DNS-only mode for first cutover.

## Phase 1: Bootstrap privately

Create a scratch deployment directory anywhere convenient, for example `~/tmp/jp-calrs`.

```bash
mkdir -p ~/tmp/jp-calrs
cd ~/tmp/jp-calrs
```

Write this bootstrap `fly.toml` with no public service section:

```toml
app = "jp-calrs"
primary_region = "yyz"

[build]
  image = "ghcr.io/olivierlambert/calrs:0.14.0"

[env]
  CALRS_BASE_URL = "https://meet.jpelletier.org"
  RUST_LOG = "calrs=info,tower_http=info"

[mounts]
  source = "calrs_data"
  destination = "/var/lib/calrs"
```

Create the app and volume:

```bash
fly apps create jp-calrs
fly volumes create calrs_data --app jp-calrs --region yyz --size 1
```

Deploy the private bootstrap release:

```bash
fly deploy
```

At this point the app is running, but there is no public HTTP service and no public booking page.

## Phase 2: Create the admin user safely

Open a shell on the running Fly machine:

```bash
fly ssh console -a jp-calrs
```

Inside the shell, run:

```bash
calrs user create --email moi@jpelletier.org --name "Jonathan Pelletier" --admin
calrs config auth --registration false
exit
```

Notes:

1. `calrs user create` will prompt for the password.
2. This flow avoids the unsafe first-web-user-admin race completely.
3. Leave registration disabled. Public guests do not need accounts to book meetings.

## Phase 3: Expose the app publicly

Replace the bootstrap `fly.toml` with this public version:

```toml
app = "jp-calrs"
primary_region = "yyz"

[build]
  image = "ghcr.io/olivierlambert/calrs:0.14.0"

[env]
  CALRS_BASE_URL = "https://meet.jpelletier.org"
  RUST_LOG = "calrs=info,tower_http=info"

[mounts]
  source = "calrs_data"
  destination = "/var/lib/calrs"

[http_service]
  internal_port = 3000
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

[[http_service.checks]]
  interval = "30s"
  timeout = "5s"
  grace_period = "10s"
  method = "GET"
  path = "/"
```

Deploy again:

```bash
fly deploy
```

## Phase 4: Attach the custom domain on Fly

Run:

```bash
fly certs add meet.jpelletier.org
fly certs setup meet.jpelletier.org
fly certs check meet.jpelletier.org
```

Use the output from `fly certs setup` for the exact DNS target and any ownership records Fly requests.

## Phase 5: Configure Cloudflare DNS

Recommended first cutover:

1. Create a `CNAME` record named `meet`
2. Point it to the Fly hostname shown by `fly certs setup` or the app's `*.fly.dev` target
3. Start with Cloudflare proxy disabled for this record

If you later want the record proxied through Cloudflare:

1. Add the `_fly-ownership` TXT record shown by Fly
2. Switch the `meet` record to proxied
3. Set Cloudflare SSL mode to `Full (strict)`

Do not publish DNS before Phase 2 is complete.

Note: this playbook uses Fly commands directly, but does not pin a specific `wrangler` DNS command sequence because `wrangler` was not available in `PATH` when this document was drafted. Use either the Cloudflare dashboard or your preferred Cloudflare CLI workflow during execution.

## Phase 6: Connect Spacemail calendar to `calrs`

Log in to `https://meet.jpelletier.org` with the admin account you created.

In the `calrs` dashboard:

1. Go to Calendar Sources
2. Add a new CalDAV source
3. Use these values:

```text
URL: https://caldav.spacemail.com/
Username: moi@jpelletier.org
Password: <Spacemail mailbox password>
```

4. Sync the source
5. Choose the destination calendar for write-back so confirmed bookings are pushed into Spacemail

## Phase 7: Configure outgoing mail from Spacemail

Open a Fly shell again:

```bash
fly ssh console -a jp-calrs
```

Inside the machine, run:

```bash
calrs config smtp \
  --host mail.spacemail.com \
  --port 465 \
  --username moi@jpelletier.org \
  --from-email moi@jpelletier.org \
  --from-name "Jonathan Pelletier"

calrs config smtp-test moi@jpelletier.org
exit
```

Use the Spacemail mailbox password if the CLI prompts for SMTP credentials.

## Phase 8: Create the first interview event type

Recommended initial settings:

1. Title: `Interview`
2. Slug: `interview`
3. Duration: `45` minutes
4. Buffer before: `15` minutes
5. Buffer after: `15` minutes
6. Minimum notice: `24` hours
7. Visibility: `Public`
8. Confirmation mode: `Off` for easy self-booking

If you want manual approval for every request, turn confirmation mode on.

## Phase 9: Verify end to end

Run this test sequence:

1. Create a busy event directly in Spacemail
2. Confirm that the same slot becomes unavailable in `calrs`
3. Open the booking page in an incognito window
4. Book a free slot
5. Confirm the booking appears in Spacemail
6. Confirm the emails are delivered from `moi@jpelletier.org`
7. Cancel the booking
8. Confirm the event is removed from Spacemail

## Operational notes

1. This is a single-machine SQLite deployment.
2. That is acceptable for a personal interview scheduler.
3. Do not scale horizontally without a replication design.
4. Keep Fly volume snapshots enabled.
5. Back up `/var/lib/calrs/calrs.db` periodically.

## Useful commands

Check status:

```bash
fly status -a jp-calrs
fly machine list -a jp-calrs
fly volumes list -a jp-calrs
fly logs -a jp-calrs
```

Check certificates:

```bash
fly certs list -a jp-calrs
fly certs check meet.jpelletier.org -a jp-calrs
```

Open a machine shell:

```bash
fly ssh console -a jp-calrs
```

## Execution checklist

1. Fly login
2. Cloudflare login
3. Create app
4. Create volume
5. Private deploy
6. Create admin
7. Disable registration
8. Public deploy
9. Attach Fly certificate
10. Add Cloudflare DNS
11. Connect Spacemail CalDAV
12. Configure Spacemail SMTP
13. Create event type
14. Verify booking flow
