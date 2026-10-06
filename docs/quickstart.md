# Lab quickstart: power on and open the dashboard

This is the commissioned laptop-side procedure for the diagnostic Polstation
dashboard. The Pi services start automatically at boot; do not manually launch
the camera, sensor, or dashboard commands.

## 1. Connect and power the system

Connect the laptop to the instrument Ethernet network, power the PoE switch and
Pi, and allow roughly 60–90 seconds for boot and camera discovery. The
commissioned laptop/Pi service addresses are:

- laptop-side network: `192.168.2.1/24`;
- Pi SSH address: `192.168.2.2`; and
- dashboard: Pi loopback `127.0.0.1:8000`, reachable only through SSH.

These addresses describe the present lab setup, not a general field-network
assignment.

## 2. Check the path from the Mac

In a Mac Terminal, run:

```sh
route -n get 192.168.2.2
ping -c 3 192.168.2.2
nc -vz -G 5 192.168.2.2 22
```

The route should use the directly connected service interface (previously
`bridge100`), ping should receive replies, and the SSH port check should say
`succeeded`. If these fail, check cable, switch/Pi power, Mac Internet Sharing or
interface configuration, and any VPN route before troubleshooting the dashboard.

## 3. Optionally verify the Pi services

This one command checks the systemd stack and loopback listener without starting
an interactive shell:

```sh
ssh admin@192.168.2.2 \
  'systemctl is-active polstation-preview.target polstation-camera-preview.service polstation-sensor-preview.service polstation-dashboard.service; systemctl --failed --no-pager; ss -ltn | grep ":8000"'
```

Expect four `active` lines, zero failed units, and a listener on
`127.0.0.1:8000`. The services run independently of SSH and the browser.

## 4. Open the SSH tunnel

In a Terminal tab that will remain open, run:

```sh
ssh \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -N \
  -L 127.0.0.1:8080:127.0.0.1:8000 \
  admin@192.168.2.2
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
ssh -o ExitOnForwardFailure=yes -N \
  -L 127.0.0.1:8081:127.0.0.1:8000 \
  admin@192.168.2.2
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
ssh admin@192.168.2.2 \
  'sudo journalctl -u polstation-camera-preview -u polstation-sensor-preview -u polstation-dashboard -n 100 --no-pager'
```

If the services are inactive but the journal shows no persistent configuration,
permission, or hardware error, restart the grouped stack and wait for camera
discovery:

```sh
ssh -t admin@192.168.2.2 \
  'sudo systemctl restart polstation-preview.target; sleep 12; systemctl is-active polstation-preview.target polstation-camera-preview.service polstation-sensor-preview.service polstation-dashboard.service'
```

Persistent failures should remain visible rather than being hidden by repeated
manual restarts. Save the journal output for diagnosis.

## Shut down safely

Close the tunnel with `Ctrl+C`, open a normal SSH shell, and stop the Pi cleanly:

```sh
ssh admin@192.168.2.2
sudo systemctl poweroff
```

Wait about 30 seconds for disk activity to stop before removing Pi or switch
power. The preview target remains enabled and starts automatically at the next
boot.
