# Eero-AdGuard-Sync
Sync Eero DHCP client list to AdGuard Home

[![Release](https://github.com/amickael/eero-adguard-sync/actions/workflows/python-publish.yml/badge.svg)](https://github.com/amickael/eero-adguard-sync/actions/workflows/python-publish.yml)
[![PyPI](https://img.shields.io/pypi/v/eero-adguard-sync?color=blue)](https://pypi.org/project/eero-adguard-sync/)
[![Code style](https://img.shields.io/badge/code%20style-black-black)](https://github.com/psf/black)

![eero-adguard-sync](https://repository-images.githubusercontent.com/445873210/a0dcb692-fe53-4e6e-83a9-4507664080c1)

Table of Contents
=================
* [Dependencies](#-dependencies)
* [Installation](#️-installation)
* [Usage](#-usage)
* [Options](#️-options)
  * [eag-sync](#eag-sync)
  * [eag-sync sync](#eag-sync-sync)
  * [eag-sync clear](#eag-sync-clear)
* [Autocompletion](#-autocompletion)
* [Docker](#-docker)
* [License](#️-license)

## 👶 Dependencies
* [Python 3.10 or higher](https://www.python.org/downloads/)

## 🛠️ Installation

### From PyPI
```shell
pip install eero-adguard-sync
```

### From source (local development)
Clone the repo and install in editable mode so your changes are reflected immediately:
```shell
git clone https://github.com/amickael/eero-adguard-sync.git
cd eero-adguard-sync
pip install -e .
```

This installs all dependencies from `requirements.txt` and registers the `eag-sync` command on your PATH. Any edits you make to the source files take effect without reinstalling.

## 🚀 Usage
**eag-sync** is a command-line program to sync your Eero DHCP client list to AdGuard Home. It is a one-way sync from Eero to AdGuard and requires Python 3.10+.

Run a sync:
```shell
eag-sync sync
```

You will be prompted for your Eero email and an SMS/email verification code on first run. Your credentials are cached locally — they never leave your computer.

To clear all locally cached credentials:
```shell
eag-sync clear
```

### Duplicate and rotating MAC handling

When a device (e.g. an iPhone with Private Wi-Fi Address) rotates its MAC address, it retains its name in Eero. The sync detects this and **updates** the existing AdGuard client with the new MAC rather than deleting and recreating it, preserving any per-client rules you have configured.

If two Eero devices share the same name (e.g. two devices both called "Living Room"), the conflicting name is automatically stripped from both clients' AdGuard identifiers so neither causes a rejection.

## ⚙️ Options

### `eag-sync`
```
Usage: eag-sync [OPTIONS] COMMAND [ARGS]...

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  sync
  clear
```

### `eag-sync sync`
```
Usage: eag-sync sync [OPTIONS]

Options:
  --adguard-host TEXT     AdGuard Home host IP address  [env: EAG_ADGUARD_HOST]
  --adguard-user TEXT     AdGuard Home username  [env: EAG_ADGUARD_USER]
  --adguard-password TEXT AdGuard Home password  [env: EAG_ADGUARD_PASS]
  --eero-user TEXT        Eero email address or phone number  [env: EAG_EERO_USER]
  --eero-cookie TEXT      Eero session cookie  [env: EAG_EERO_COOKIE]
  -d, --delete            Delete AdGuard clients not found in Eero DHCP list
                          [env: EAG_DELETE]
  -y, --confirm           Skip interactive confirmation  [env: EAG_CONFIRM]
  -o, --overwrite         Delete all AdGuard clients before sync
                          [env: EAG_OVERWRITE]
  -x, --exclude-range TEXT
                          CIDR range(s) protected from deletion when --delete
                          is active (e.g. 192.168.1.0/24). Repeatable.
                          Env var: comma-separated string.  [env: EAG_EXCLUDE_RANGE]
  -e, --exclude-id TEXT   Client identifier(s) protected from deletion when
                          --delete is active. Accepts MAC address, client name,
                          or hostname. Supports wildcards and regex (re: prefix).
                          Repeatable. Env var: comma-separated string.  [env: EAG_EXCLUDE_ID]
  --debug                 Display debug information
  --no-global-id TEXT     Client identifier(s) always registered in AdGuard with
                          'Use global settings' disabled. Accepts MAC address,
                          client name, or hostname. Supports wildcards and regex
                          (re: prefix). Repeatable.
                          Env var: comma-separated string.  [env: EAG_NO_GLOBAL_ID]
  --help                  Show this message and exit.
```

#### Per-client AdGuard settings

`--no-global-id` registers specific devices in AdGuard with **"Use global settings" turned off**, letting you configure per-client DNS rules, blocked services, or upstream resolvers for those devices without affecting the rest of the network. Unlike `--exclude-id`, the device is still fully synced (name, IPs, tags) — only `use_global_settings` is pinned to `false`.

Patterns are matched against the client's **nickname** only. Plain patterns use shell-style wildcards (`*`, `?`). Prefix a pattern with `re:` to use a Python regex instead.

```shell
# Pin by device name
eag-sync sync --no-global-id "Alice's iPad"

# Pin by MAC address
eag-sync sync --no-global-id "aa-bb-cc-dd-ee-ff"

# Pin multiple devices
eag-sync sync --no-global-id "Alice's iPad" --no-global-id "Alice's iPhone"

# Wildcard — all devices whose name starts with a prefix
eag-sync sync --no-global-id "Alice*"

# Regex — all devices starting with "Alice" except "Alice's HomePod"
eag-sync sync --no-global-id "re:^Alice(?!.*HomePod)"

# Or via env var (comma-separated)
# EAG_NO_GLOBAL_ID="Alice's iPad,Alice's iPhone"
# EAG_NO_GLOBAL_ID="re:^Alice(?!.*HomePod)"
```

#### Protecting clients from deletion

When running with `--delete`, you can protect specific clients from being removed. Both plain wildcards (`*`, `?`) and `re:` prefixed Python regex are supported.

```shell
# Protect an entire subnet
eag-sync sync --delete --exclude-range 192.168.1.0/24

# Protect a specific device by MAC address
eag-sync sync --delete --exclude-id "11:22:33:44:55:66"

# Protect a device by its AdGuard client name
eag-sync sync --delete --exclude-id "My Device"

# Protect all devices whose name starts with a prefix (wildcard)
eag-sync sync --delete --exclude-id "my-prefix*"

# Regex — protect all devices starting with "Alice" except "Alice's HomePod"
eag-sync sync --delete --exclude-id "re:^Alice(?!.*HomePod)"

# Combine multiple protections
eag-sync sync --delete \
  --exclude-range 192.168.2.0/24 \
  --exclude-id "11:22:33:44:55:66" \
  --exclude-id "my-server"
```

This is useful for:
- Devices with custom AdGuard rules (blocked services, custom upstreams) that you don't want reset
- Devices that are temporarily offline at sync time
- Static IP devices outside the Eero DHCP range

### `eag-sync clear`
```
Usage: eag-sync clear [OPTIONS]

Options:
  -y, --confirm  Skip interactive confirmation
  --help         Show this message and exit.
```


## 🔮 Autocompletion

### bash
Add to `~/.bashrc`:
```shell
eval "$(_EAG_SYNC_COMPLETE=bash_source eag-sync)"
```

### zsh
Add to `~/.zshrc`:
```shell
eval "$(_EAG_SYNC_COMPLETE=zsh_source eag-sync)"
```

## 🐋 Docker

A Docker image that executes `eag-sync sync` on a `cron` schedule is available on Docker Hub: [`amickael/eero-adguard-sync`](https://hub.docker.com/repository/docker/amickael/eero-adguard-sync).

All configuration is passed via environment variables. Every CLI option has a corresponding env var — see the table below.

| Variable | Description | Required | Default |
|---|---|---|---|
| `EAG_EERO_COOKIE` | Eero session cookie (from `eag-sync sync --debug`) | Yes | |
| `EAG_ADGUARD_HOST` | AdGuard Home host IP address | Yes | |
| `EAG_ADGUARD_USER` | AdGuard admin username | Yes | |
| `EAG_ADGUARD_PASS` | AdGuard admin password | Yes | |
| `EAG_DELETE` | Enable deletion of AdGuard clients not in Eero (`true`/`1`) | No | |
| `EAG_OVERWRITE` | Wipe all AdGuard clients before sync (`true`/`1`) | No | |
| `EAG_CONFIRM` | Skip interactive confirmation (`true`/`1`) | No | |
| `EAG_EXCLUDE_RANGE` | Comma-separated CIDR ranges protected from deletion | No | |
| `EAG_EXCLUDE_ID` | Comma-separated client identifiers (MAC, name, hostname) protected from deletion | No | |
| `EAG_NO_GLOBAL_ID` | Comma-separated client identifiers always given per-client AdGuard settings (MAC, name, or hostname, wildcards ok) | No | |
| `EAG_CRON_SCHEDULE` | Sync schedule in cron syntax | No | `0 0 * * *` |

### Example `docker run`

```shell
docker run -d \
  -e EAG_EERO_COOKIE="your-cookie" \
  -e EAG_ADGUARD_HOST="192.168.1.1" \
  -e EAG_ADGUARD_USER="admin" \
  -e EAG_ADGUARD_PASS="password" \
  -e EAG_DELETE="true" \
  -e EAG_CONFIRM="true" \
  -e EAG_EXCLUDE_RANGE="192.168.1.0/24" \
  -e EAG_EXCLUDE_ID="11:22:33:44:55:66,my-server" \
  -e EAG_CRON_SCHEDULE="0 * * * *" \
  amickael/eero-adguard-sync
```

### Example `docker-compose.yml`

```yaml
services:
  eero-adguard-sync:
    image: amickael/eero-adguard-sync
    environment:
      EAG_EERO_COOKIE: "your-cookie"
      EAG_ADGUARD_HOST: "192.168.1.1"
      EAG_ADGUARD_USER: "admin"
      EAG_ADGUARD_PASS: "password"
      EAG_DELETE: "true"
      EAG_CONFIRM: "true"
      EAG_EXCLUDE_RANGE: "192.168.1.0/24"
      EAG_EXCLUDE_ID: "11:22:33:44:55:66,my-server"
      EAG_NO_GLOBAL_ID: "Alice's iPad,Alice's iPhone"
      EAG_CRON_SCHEDULE: "0 * * * *"
    restart: unless-stopped
```

## 🔄 Migration

### `EAG_SYNC_FLAGS` (deprecated)

Older deployments used `EAG_SYNC_FLAGS` to pass raw CLI flags to the sync script (e.g. `EAG_SYNC_FLAGS="-y -d"`). This is still supported for backwards compatibility, but is superseded by the individual env vars.

| Old | New |
|---|---|
| `EAG_SYNC_FLAGS="-y"` | `EAG_CONFIRM=true` |
| `EAG_SYNC_FLAGS="-d"` | `EAG_DELETE=true` |
| `EAG_SYNC_FLAGS="-y -d"` | `EAG_CONFIRM=true` + `EAG_DELETE=true` |

## ⚖️ License
[MIT © 2022 Andrew Mickael](https://github.com/amickael/eero-adguard-sync/blob/master/LICENSE)
