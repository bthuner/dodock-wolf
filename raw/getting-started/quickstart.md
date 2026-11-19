# Quickstart

> Install the Wolf App, put an agent on the host and get a first alert, on one bench.

This guide sets up Dodock Wolf on one bench: the Wolf App on one site, the Wolf Agent on the
host, and an email alert for 502 spikes. Plan an afternoon.

**You need:** a Frappe 15 or Dokos (Dodock 5) bench, Node 20.19 or later for `bench build`, root on
the host, and a site that will hold Wolf's data (it can be an existing site).

<steps level="3">

### Install the Wolf App

```bash [bench]
cd ~/frappe-bench
bench get-app https://github.com/bthuner/dodock-wolf
bench --site wolf.example.com install-app dodock_wolf
bench build --app dodock_wolf
```

Installing creates the roles **Wolf Manager** and **Wolf User**, a registration token and the
[preset alert rules](/alerts/presets).

### Run the scheduler every minute

Wolf evaluates rules every minute, but Frappe 15 and Dodock tick every 4 minutes by default.

```bash [bench]
bench set-config -g scheduler_tick_interval 60
# then restart the bench's scheduler process (supervisor or systemd)
```

<warning>

Without this, an alert can come up to 4 minutes late, and "fire after 3 evaluations" means
12 minutes. The Wolf UI's **Monitoring** page shows the pace in use.

</warning>

### Install the agent on the host

Open **Wolf Settings → Agent install command** and copy the one-liner. It looks like this:

```bash [host]
curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
  | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<registration token> bash
```

The script installs the agent in `/opt/wolf-agent` (linked as `/usr/local/bin/wolf-agent`), creates a `wolf-agent` system user, registers the host, writes
`/etc/wolf-agent/config.json` and starts `wolf-agent.service`. It finds your benches by itself.

### Check what the agent sees

```bash [host]
sudo -u wolf-agent wolf-agent discover
sudo -u wolf-agent wolf-agent check --status
```

`discover` lists benches, sites and log paths. `check` collects once and prints the JSON it would
send, without sending it. `--status` also asks the site for its health.

### Add a channel to a rule

Presets open incidents but notify nobody until you add a channel. Open **Wolf Alert Rule → 502
spike after deployment**, add a row to **Channels** (type *Email*, your address), save, then
click **Send test notification**.

See [Channels](/alerts/channels) for Slack, Raven, PagerDuty and the other types.

### Open the Wolf UI

Go to `https://wolf.example.com/wolf`. The overview lists hosts, benches and sites with their
latest metrics and open incidents. Within a minute of the first push, the host shows up.

For a Wolf Manager, **Set up Wolf** at the top says what is left before Wolf can wake someone up,
each step read from the site itself: an agent registered and reporting, its host setup without a
failure, the scheduler at one minute, rules on, a rule with a channel, and a test notification a
channel accepted. The list leaves the overview once every step is done; the **Monitoring** page
keeps it.

To look at one moment, select a range on the **HTTP responses** chart: drag across it, or click
its first and last point (with the keyboard: arrow keys, then Enter twice). The chart, the
figures under **In this window** and the Events and Errors pages opened from them then cover
that range. The figures under **Now**, the signals and the list of hosts always show the present.
**Back to a relative window** returns to the last 24 hours.

</steps>

## Mark your deployments

Rules such as *502 spike after deployment* only fire when a deployment hit the same scope recently.
Bench migrations on the Wolf site, and Press and Pilot tasks, are recorded by themselves. For other
benches, add one line to your deploy script:

```bash [deploy.sh]
sudo -u wolf-agent wolf-agent mark-deployment --bench frappe-bench --note "v5.18.2" --silence 15m
```

The config holding the agent's secret is readable by `wolf-agent` only, hence `sudo -u`.
`--silence 15m` also opens a [maintenance window](/alerts/rules#maintenance-windows): incidents
keep opening during the deploy, but their notifications wait until it ends.

## Next

- Watch the other sites of the bench: [Every site on a bench](/install/every-site).
- Tune what the agent collects: [Configuration](/agent/configuration).
- Write your own rules: [Alert rules](/alerts/rules).
