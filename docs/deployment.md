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
sudo install -d -o polstation -g polstation -m 0750 /var/lib/polstation/data
sudo install -d -o polstation -g polstation -m 0750 /var/lib/polstation/state
sudo install -d -o root -g polstation -m 0750 /etc/polstation
sudo install -d -o "$USER" -g "$(id -gn)" /opt/polstation
install -d /opt/polstation/releases
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
.venv/bin/python -m pip install '.[sensor-preview]'
.venv/bin/python -m pip install /opt/alliedvision/VimbaX_2026-2/api/python/vmbpy-1.2.2-py3-none-manylinux_2_27_aarch64.whl
.venv/bin/python -m unittest discover -s tests -v
git rev-parse HEAD
```

The proprietary VmbPy wheel and GenTL path above are the versions commissioned
on this Pi. Verify both paths whenever Vimba X changes; do not silently substitute
a different SDK release.

For the first install only, copy the field template:

```sh
sudo install -o root -g polstation -m 0640 config/example_field_config.yaml /etc/polstation/config.yaml
sudo install -o root -g polstation -m 0640 deploy/systemd/polstation-vimbax.env.example /etc/polstation/vimbax.env
sudoedit /etc/polstation/config.yaml
sudoedit /etc/polstation/vimbax.env
```

Set `provenance.git_commit` to the full SHA printed above, `release_tag` to the
selected tag, and `calibration_id` when commissioned. Copy only the verified
camera IDs/angles, BME280 bus/address and stable EPEVER `/dev/serial/by-id/`
settings from the ignored commissioning configuration. Keep `data_root` and
`state_root` under `/var/lib/polstation`. For updates, back up the existing
configuration and edit it rather than replacing it with a fresh template. Record
which config backup belongs to the preceding release for rollback.

```sh
sudo -u polstation /opt/polstation/releases/v0.1.0/.venv/bin/polstation-check-config --config /etc/polstation/config.yaml
```

## 4. Activate and verify the unattended recording stack

For updates, stop both mutually exclusive targets before changing the active
link. On first install, there are no services to stop. Preserve the previous link target
(`readlink /opt/polstation/current`) and configuration before activation.

```sh
# Updates only:
sudo systemctl stop polstation-recording.target polstation-preview.target
# First install and updates:
sudo ln -sfn /opt/polstation/releases/v0.1.0 /opt/polstation/current

# Commissioned 192.168.2.0/24 + camera link-local lab network only:
sudo install -o root -g root -m 0755 \
    deploy/networkmanager/90-polstation-camera-address \
    /etc/NetworkManager/dispatcher.d/90-polstation-camera-address
sudo /etc/NetworkManager/dispatcher.d/90-polstation-camera-address \
    eth0 dhcp4-change

for name in camera-preview sensor-preview dashboard observation-recorder system-summary; do
    sed 's|@INSTALL_ROOT@|/opt/polstation/current|g' \
        "deploy/systemd/polstation-${name}.service.in" \
        | sudo tee "/etc/systemd/system/polstation-${name}.service" >/dev/null
done
sudo install -o root -g root -m 0644 \
    deploy/systemd/polstation-preview.target \
    /etc/systemd/system/polstation-preview.target
sudo install -o root -g root -m 0644 \
    deploy/systemd/polstation-recording.target \
    /etc/systemd/system/polstation-recording.target
sudo install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d
sudo install -o root -g root -m 0644 \
    deploy/journald/90-polstation-persistent.conf \
    /etc/systemd/journald.conf.d/90-polstation-persistent.conf
sudo systemd-analyze verify \
    /etc/systemd/system/polstation-camera-preview.service \
    /etc/systemd/system/polstation-sensor-preview.service \
    /etc/systemd/system/polstation-dashboard.service \
    /etc/systemd/system/polstation-observation-recorder.service \
    /etc/systemd/system/polstation-system-summary.service \
    /etc/systemd/system/polstation-preview.target \
    /etc/systemd/system/polstation-recording.target
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo systemctl disable polstation-preview.target
sudo systemctl enable --now polstation-recording.target
sudo systemctl status \
    polstation-observation-recorder \
    polstation-sensor-preview \
    polstation-dashboard \
    polstation-system-summary
sudo journalctl \
    -u polstation-observation-recorder \
    -u polstation-sensor-preview \
    -u polstation-dashboard \
    -n 100 --no-pager
```

The timed recorder is the unattended default. It uses bounded shared-auto test
frames before each immutable capture; fixed 15 ms remains an explicit option.
It conflicts with camera preview because both require exclusive camera
ownership. See [operations](operations.md) for controlled switching.

The two diagnostic producers can write only the replaceable state directory; the
dashboard has read-only access. The separately activated recorder can write the
data and state roots. `SupplementaryGroups=i2c dialout` grants the sensor
producer the permissions already verified during commissioning. The Vimba camera
producer and recorder load `/etc/polstation/vimbax.env`. The service account does
not own or modify release code. The preview target remains an optional
diagnostic mode and does not start the recorder.

The NetworkManager hook above is specific to the commissioned temporary lab
addressing described in the [Pi/Vimba X bring-up record](commissioning/2026-09-28-pi5-vimbax-camera-bring-up.md).
It keeps the DHCP service address ahead of `169.254.68.1/16`, as required by the
tested Vimba X discovery behavior. Do not install it on a differently addressed
field network without reviewing the interface and subnet values.

## 5. View the dashboard from the laptop

Run this on your laptop and keep the tunnel open:

```sh
ssh \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -N \
  -L 127.0.0.1:8080:127.0.0.1:8000 \
  pi@<Pi-address>
```

Replace `<Pi-address>` with the commissioned Pi address. A successful command
remains silent and must stay running. Open <http://127.0.0.1:8080/> on the laptop.
SSH provides authentication and transport protection. Do not expose the
dashboard HTTP server directly to the network. The commissioned lab procedure
and troubleshooting checks are in the [quickstart](quickstart.md).

## Rollback

Stop both `polstation-recording.target` and `polstation-preview.target`, restore the preceding release's configuration
(including its provenance), and change `/opt/polstation/current` back to its
recorded release directory using `sudo ln -sfn`. If unit templates changed,
restore the preceding units and run `sudo systemctl daemon-reload`. Restart the
target and verify the reported commit and health. Retain prior release directories
and venvs.
Scientific data stays under `/var/lib/polstation/data` throughout; do not run
`git clean` or data deletion as part of deployment. Future data/config schema
changes must have a migration and rollback plan before release.

## External Ethernet service access

The planned service path is laptop → external panel RJ45 → TSW101 network,
with the Raspberry Pi 5 and all three Mako cameras on that network. No desktop,
monitor, X11 forwarding or VNC is needed on the Pi. Closing the SSH session or
browser leaves the systemd-managed preview producers running.

Commission a private static subnet so service access does not require DHCP.
An example only is Pi `192.168.50.10/24`, cameras `.21`–`.23`, and laptop
`192.168.50.100/24`. Confirm address conflicts, actual switch wiring and the
camera addressing procedure before applying any network settings. The scaffold
does not configure Ethernet interfaces or camera addresses. Local service access
does not require Internet; fetching GitHub releases and dependencies does require
a separate Internet path or an offline release-transfer procedure.
