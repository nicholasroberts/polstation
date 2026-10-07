# Lab quickstart: power on and open the dashboard

This is the commissioned laptop-side procedure for the diagnostic Polstation
dashboard. The Pi services start automatically at boot; do not manually launch
the camera, sensor, or dashboard commands.

## 1. Connect and power the system

On the Mac, enable Internet Sharing to the USB Ethernet adapter used by the
instrument. Connect the laptop to TSW101 port 5, power the PoE switch and Pi,
and allow roughly 60–90 seconds for boot and camera discovery. If the Pi was
already powered before Internet Sharing was enabled, unplug and reconnect the
Mac Ethernet adapter or toggle Internet Sharing off and on once. The stable
connection names and addresses are:

- laptop-side network: `192.168.2.1/24`;
- Pi SSH hostname: `polstation.local` (mDNS, usable over IPv4 or IPv6);
- Pi DHCP IPv4 address: optional and not fixed;
- Pi camera-side address: `169.254.68.1/16`; and
- dashboard: Pi loopback `127.0.0.1:8000`, reachable only through SSH.

Do not assume that the Pi is `192.168.2.2`. Mac Internet Sharing has assigned
that address during some sessions, but it can assign a different address or no
IPv4 lease at all. The Pi remains reachable as `polstation.local` when mDNS and
IPv6 are working. These values describe the present lab setup, not a general
field-network assignment.

## 2. Check the path from the Mac

In a Mac Terminal, check the service interface and SSH by hostname:

```sh
ifconfig bridge100 | grep 'inet ' || echo "bridge100 has no IPv4 address"
nc -vz -G 10 polstation.local 22
```

The SSH port check should say `succeeded`. A failed `ping` or the absence of a Pi
IPv4 lease is not conclusive because SSH may be using the Pi's mDNS-resolved IPv6
address. Use the SSH port check as the connection test.

If `polstation.local` is not found immediately, wait another 30 seconds and
retry. To watch mDNS resolution directly, run the following, wait for an address
to appear, and then press `Ctrl+C`:

```sh
dns-sd -G v4v6 polstation.local
```

If it still does not resolve, check cable, switch/Pi power, Mac Internet Sharing,
the USB Ethernet interface, and any VPN before troubleshooting the dashboard.
For diagnosis only, `arp -an | grep bridge100` may reveal a current DHCP IPv4
address. Use such an address only for that session; do not save it as the normal
connection target.

## 3. Optionally verify the Pi services

This one command checks the systemd stack and loopback listener without starting
an interactive shell:

```sh
ssh -o ConnectTimeout=10 admin@polstation.local \
  'systemctl is-active polstation-preview.target polstation-camera-preview.service polstation-sensor-preview.service polstation-dashboard.service; systemctl --failed --no-pager; ss -ltn | grep ":8000"'
```

Expect four `active` lines and a listener on `127.0.0.1:8000`. Normally there
are zero failed units. The services run independently of SSH and the browser.

On the currently deployed release,
`NetworkManager-wait-online.service` can be failed if the Pi booted before the
Mac supplied DHCP. That does not by itself mean the Polstation services or
dashboard have failed; use the four explicit service states and port check
above. The next release removes this unnecessary boot dependency.

## 4. Open the SSH tunnel

In a Terminal tab that will remain open, run:

```sh
ssh \
  -o ConnectTimeout=10 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -N \
  -L 127.0.0.1:8080:127.0.0.1:8000 \
  admin@polstation.local
```

Enter the Pi password. A successful `ssh -N` command displays no prompt or
success message and continues running. Leave that Terminal tab open. In the
browser, use HTTP—not HTTPS—and open:

<http://127.0.0.1:8080/>

Closing the browser or pressing `Ctrl+C` in the tunnel Terminal closes only the
tunnel. It does not stop acquisition previews or the Pi services.

## Troubleshooting

### Local port 8080 is already occupied

Check it on the Mac:

```sh
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

If another required process owns it, use laptop port 8081 instead:

```sh
ssh -o ConnectTimeout=10 -o ExitOnForwardFailure=yes -N \
  -L 127.0.0.1:8081:127.0.0.1:8000 \
  admin@polstation.local
```

Then open <http://127.0.0.1:8081/>.

### The tunnel stays open but the browser cannot connect

Leave the tunnel running and test it from another Mac Terminal:

```sh
curl --fail --show-error http://127.0.0.1:8080/api/previews >/dev/null \
  && echo "Dashboard API reachable"
```

If this fails, repeat the remote service check from step 3. Inspect the journals
before restarting anything:

```sh
ssh admin@polstation.local \
  'sudo journalctl -u polstation-camera-preview -u polstation-sensor-preview -u polstation-dashboard -n 100 --no-pager'
```

If the services are inactive but the journal shows no persistent configuration,
permission, or hardware error, restart the grouped stack and wait for camera
discovery:

```sh
ssh -t admin@polstation.local \
  'sudo systemctl restart polstation-preview.target; sleep 12; systemctl is-active polstation-preview.target polstation-camera-preview.service polstation-sensor-preview.service polstation-dashboard.service'
```

Persistent failures should remain visible rather than being hidden by repeated
manual restarts. Save the journal output for diagnosis.

### The dashboard works but all cameras are absent

First confirm that the camera producer reports `expected three cameras, found
0`, then stop it before running the Vimba diagnostic executable:

```sh
ssh admin@polstation.local
sudo systemctl stop polstation-camera-preview.service
ip -brief address show eth0
/opt/alliedvision/VimbaX_2026-2/bin/ListCameras_VmbC
```

If `eth0` has a DHCP service address as well as `169.254.68.1/16`, the DHCP
address must be listed first for the Vimba X behavior observed during
commissioning. If the two addresses appear in the opposite order, restore the
tested ordering and retry discovery:

```sh
sudo ip address delete 169.254.68.1/16 dev eth0
sudo ip address add 169.254.68.1/16 dev eth0
ip -brief address show eth0
/opt/alliedvision/VimbaX_2026-2/bin/ListCameras_VmbC
sudo systemctl start polstation-camera-preview.service
```

Green switch-port lights establish power and Ethernet link only. In the 2026-10-06
test, all three cameras answered ping and GigE Vision discovery, but Vimba X
reported zero cameras until the IPv4 addresses were reordered.

If no DHCP IPv4 lease is present, `eth0` may correctly show only
`169.254.68.1/16` plus IPv6 addresses. That is sufficient for the link-local
camera network; use `polstation.local` rather than a guessed DHCP address for
SSH access.

## Shut down safely

Close the tunnel with `Ctrl+C`, open a normal SSH shell, and stop the Pi cleanly:

```sh
ssh admin@polstation.local
sudo systemctl poweroff
```

Wait about 30 seconds for disk activity to stop before removing Pi or switch
power. The preview target remains enabled and starts automatically at the next
boot.
