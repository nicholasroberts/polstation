# Local repository → GitHub → Raspberry Pi

The laptop is the development workspace. GitHub stores reviewed commits and
release tags. The Pi installs one selected tag and keeps its local configuration
and data separately. `git commit` is local; `git push` uploads; neither deploys.
No unattended updater is included. The commands below are operator-run examples,
not actions already performed by the scaffold.

## 1. Develop and share

From a clean local checkout, first synchronize and create a feature branch:

```sh
git switch main
git pull --ff-only
git switch -c codex/initial-scaffold
```

If edits already exist, create the feature branch before committing; do not pull
over unreviewed work. Implement changes, then:

```sh
. .venv/bin/activate
python -m unittest discover -s tests -v
git status --short
git diff
# Explicitly stage the intended software and template files.
git add src config tests docs scripts deploy pyproject.toml README.md .gitignore
git commit -m "Add initial instrument scaffold"
git push -u origin codex/initial-scaffold
```

Open and review a pull request on GitHub. After merging, update local main and
create an annotated tag at the tested commit. Example only: `v0.1.0` would identify
this scaffold, not a camera-ready release.

```sh
git switch main
git pull --ff-only
python -m unittest discover -s tests -v
git tag -a v0.1.0 -m "Initial scaffold; no hardware acquisition"
git push origin v0.1.0
```

Never move a published deployment tag; create a new release instead. A GitHub
Release may attach notes to the tag. Before field deployment, also pin and archive
the tested dependency set for the Pi platform; a Git tag alone does not freeze
third-party packages or the operating system.

## 2. Prepare the Pi once

Use a Pi OS with Python 3.11+, git and Python venv support. SSH into the Pi using
your actual hostname and account. For a private repository, provision a read-only
GitHub deploy key for that login account; the runtime service needs no GitHub key.
Verify the repository's visibility in GitHub settings if privacy is required.

```sh
ssh pi@polstation
sudo apt-get update
sudo apt-get install git python3-venv
sudo useradd --system --user-group --home-dir /var/lib/polstation --shell /usr/sbin/nologin polstation
sudo install -d -o polstation -g polstation -m 0750 /var/lib/polstation
sudo install -d -o root -g polstation -m 0750 /etc/polstation
sudo install -d -o "$USER" -g "$(id -gn)" /opt/polstation/releases
git clone git@github.com:nicholasroberts/polstation.git /opt/polstation/repository
```

Skip user creation if that service account already exists. Keep release code in
`/opt`, not under a home directory: the units enable `ProtectHome=true`.

## 3. Stage a release without disturbing the running one

Use a fresh directory and venv for each release so rollback retains the previous
code and dependencies. These examples use tag `v0.1.0`; substitute the tag you
actually published.

```sh
git -C /opt/polstation/repository fetch origin --tags
git -C /opt/polstation/repository worktree add --detach /opt/polstation/releases/v0.1.0 v0.1.0
cd /opt/polstation/releases/v0.1.0
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m unittest discover -s tests -v
git rev-parse HEAD
```

For the first install only, copy the field template:

```sh
sudo install -o root -g polstation -m 0640 config/example_field_config.yaml /etc/polstation/config.yaml
sudoedit /etc/polstation/config.yaml
```

Set `provenance.git_commit` to the full SHA printed above, `release_tag` to the
selected tag, and `calibration_id` when commissioned. Leave unverified hardware
parameters null. For updates, back up the existing configuration and edit it
rather than replacing it with a fresh template. Record which config backup
belongs to the preceding release for rollback.

```sh
sudo -u polstation /opt/polstation/releases/v0.1.0/.venv/bin/polstation-check-config --config /etc/polstation/config.yaml
```

## 4. Activate and verify

For updates, stop both services before changing the active link. On first install,
there are no services to stop. Preserve the previous link target (`readlink
/opt/polstation/current`) and configuration before activation.

```sh
# Updates only:
sudo systemctl stop polstation-acquisition polstation-dashboard
# First install and updates:
sudo ln -sfn /opt/polstation/releases/v0.1.0 /opt/polstation/current
sed 's|@INSTALL_ROOT@|/opt/polstation/current|g' deploy/systemd/polstation-acquisition.service.in | sudo tee /etc/systemd/system/polstation-acquisition.service >/dev/null
sed 's|@INSTALL_ROOT@|/opt/polstation/current|g' deploy/systemd/polstation-dashboard.service.in | sudo tee /etc/systemd/system/polstation-dashboard.service >/dev/null
sudo systemd-analyze verify /etc/systemd/system/polstation-acquisition.service /etc/systemd/system/polstation-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now polstation-acquisition polstation-dashboard
sudo systemctl status polstation-acquisition polstation-dashboard
sudo journalctl -u polstation-acquisition -n 50 --no-pager
```

The acquisition unit can write `/var/lib/polstation`; the dashboard filesystem is
read-only. The service account should not own or modify release code. No hardware
groups are granted yet because no drivers run. Review device access when adding
I2C and serial drivers.

## 5. View the dashboard from the laptop

Run this on your laptop and keep the tunnel open:

```sh
ssh -N -L 8080:127.0.0.1:8000 pi@<Pi-address>
```

Replace `<Pi-address>` with the commissioned Pi address. Open http://localhost:8080 on the laptop. SSH provides authentication and transport
protection. Do not expose the scaffold HTTP server directly to the network.

## Rollback

Stop both services, restore the preceding release's configuration (including its
provenance), and change `/opt/polstation/current` back to its recorded release
directory using `sudo ln -sfn`. If unit templates changed, restore the preceding
units and run `sudo systemctl daemon-reload`. Restart both services and verify
the reported commit and health. Retain prior release directories and venvs.
Scientific data stays under `/var/lib/polstation/data` throughout; do not run
`git clean` or data deletion as part of deployment. Future data/config schema
changes must have a migration and rollback plan before release.

## External Ethernet service access

The planned service path is laptop → external panel RJ45 → TSW101 network,
with the Raspberry Pi 5 and all three Mako cameras on that network. No desktop,
monitor, X11 forwarding or VNC is needed on the Pi. Closing the SSH session or
browser leaves the systemd acquisition service running.

Commission a private static subnet so service access does not require DHCP.
An example only is Pi `192.168.50.10/24`, cameras `.21`–`.23`, and laptop
`192.168.50.100/24`. Confirm address conflicts, actual switch wiring and the
camera addressing procedure before applying any network settings. The scaffold
does not configure Ethernet interfaces or camera addresses. Local service access
does not require Internet; fetching GitHub releases and dependencies does require
a separate Internet path or an offline release-transfer procedure.
