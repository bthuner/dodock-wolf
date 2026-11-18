# Wolf Agent

> Install the host daemon, register it with the Wolf site and check what it collects.

The Wolf Agent is a Python daemon (3.9 or later, standard library only). Install one per host:
it watches every bench on that host.

## One-line install

Copy the command from **Wolf Settings → Agent install command**, or write it yourself:

```bash [host]
curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
  | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<registration token> bash
```

From a checkout of the repository:

```bash [host]
sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<registration token> ./agent/install.sh
```

The script:

1. creates a venv in `/opt/wolf-agent` and links `/usr/local/bin/wolf-agent`;
2. creates the system user `wolf-agent` and adds it to `adm`, `systemd-journal` and `frappe` when
those groups exist, so it reads auth, nginx and bench logs without root;
3. registers the host and writes `/etc/wolf-agent/config.json` (mode 0600);
4. installs and starts `wolf-agent.service`;
5. on a [Frappe Pilot](/install/pilot) host, installs `wolf-pilot-export`, a root timer that copies
the bench's task and process states the agent cannot read itself.

## Install options

<table>
<thead>
  <tr>
    <th>
      Variable
    </th>
    
    <th>
      Effect
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        WOLF_URL
      </code>
    </td>
    
    <td>
      The central Wolf site.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        WOLF_TOKEN
      </code>
    </td>
    
    <td>
      Its registration token (<strong>
        Wolf Settings
      </strong>
      
      ).
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        WOLF_BENCHES
      </code>
    </td>
    
    <td>
      Space-separated bench paths, to skip auto-discovery: <code>
        "/home/frappe/frappe-bench /srv/other-bench"
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        WOLF_AGENT_SRC
      </code>
    </td>
    
    <td>
      pip source: a local directory or a <code>
        git+https
      </code>
      
       URL. Default: the script's directory, or GitHub when piped from curl.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        WOLF_AGENT_REF
      </code>
    </td>
    
    <td>
      Git ref when installing from GitHub. Default <code>
        main
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        WOLF_INSECURE=1
      </code>
    </td>
    
    <td>
      Skip TLS verification during registration and pushes (self-signed Wolf site).
    </td>
  </tr>
</tbody>
</table>

Without `WOLF_URL` and `WOLF_TOKEN`, the agent is installed but not registered. Register it later:

```bash [host]
sudo wolf-agent --config /etc/wolf-agent/config.json register --url https://wolf.example.com --token <token>
sudo chown wolf-agent: /etc/wolf-agent/config.json && sudo systemctl start wolf-agent
```

Without systemd (a container), the script prints the command to run as `wolf-agent`.

## Bench discovery

The agent finds benches by itself:

- a `bench.toml`, or a directory with `sites/` and `apps/frappe`;
- [Pilot benches](/install/pilot), read with Pilot's real `bench.toml` schema;
- [Press servers](/install/press), detected from `/home/frappe/agent/config.json`.

```bash [host]
sudo -u wolf-agent wolf-agent discover
```

## Check it

```bash [host]
sudo -u wolf-agent wolf-agent doctor           # what this host gives the agent, and what to fix
sudo -u wolf-agent wolf-agent check            # collect once, print the payload, send nothing
sudo -u wolf-agent wolf-agent check --status   # also ask the site for its health
journalctl -u wolf-agent -f
```

Within a minute the host appears in the Wolf UI. On the Wolf site it is a **Wolf Agent** record
(`WAG-0001`…) carrying its host name.

## Credentials

The agent's secret is shown once, at registration. The site keeps only a salted HMAC-SHA256 hash.
To move an agent or recover a lost config, click **Rotate secret** on the **Wolf Agent** form, or
register the host again.

If the site rejects the credentials (401 or 403), the agent sends a last [watchdog](/agent/watchdog)
alert and exits with status 2, and systemd stops restarting it.

## Next

- [What is collected](/agent/collected)
- [Configuration](/agent/configuration)
