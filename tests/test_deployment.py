"""Keep the diagnostic systemd boundary aligned with the commissioned design."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy/systemd"
NETWORKMANAGER = ROOT / "deploy/networkmanager"


class DeploymentTests(unittest.TestCase):
    def read(self, name):
        return (SYSTEMD / name).read_text()

    def test_preview_target_owns_three_independent_services(self):
        target = self.read("polstation-preview.target")
        for name in ("camera-preview", "sensor-preview", "dashboard"):
            self.assertIn(f"polstation-{name}.service", target)

    def test_preview_services_use_release_config_and_bounded_state(self):
        expected_commands = {
            "polstation-camera-preview.service.in": "polstation-camera-preview",
            "polstation-sensor-preview.service.in": "polstation-sensor-preview",
            "polstation-dashboard.service.in": "polstation-dashboard",
        }
        for filename, command in expected_commands.items():
            with self.subTest(filename=filename):
                unit = self.read(filename)
                self.assertIn("User=polstation", unit)
                self.assertIn("WorkingDirectory=@INSTALL_ROOT@", unit)
                self.assertIn(f"@INSTALL_ROOT@/.venv/bin/{command}", unit)
                self.assertIn("--config /etc/polstation/config.yaml", unit)
                self.assertIn("PartOf=polstation-preview.target", unit)
                self.assertIn("Restart=always", unit)
                self.assertIn("ProtectSystem=strict", unit)
                self.assertIn("ProtectHome=true", unit)
                self.assertNotIn("/home/", unit)

        self.assertIn("ReadWritePaths=/var/lib/polstation/state",
                      self.read("polstation-camera-preview.service.in"))
        self.assertIn("ReadWritePaths=/var/lib/polstation/state",
                      self.read("polstation-sensor-preview.service.in"))
        self.assertIn("ReadOnlyPaths=/var/lib/polstation",
                      self.read("polstation-dashboard.service.in"))

    def test_hardware_specific_permissions_stay_narrow(self):
        camera = self.read("polstation-camera-preview.service.in")
        sensors = self.read("polstation-sensor-preview.service.in")
        dashboard = self.read("polstation-dashboard.service.in")
        self.assertIn("EnvironmentFile=/etc/polstation/vimbax.env", camera)
        self.assertIn("SupplementaryGroups=i2c dialout", sensors)
        self.assertNotIn("SupplementaryGroups", dashboard)
        self.assertIn("--hardware-preview", dashboard)
        self.assertIn("PrivateDevices=true", dashboard)

    def test_preview_stack_does_not_block_on_external_network(self):
        target = self.read("polstation-preview.target")
        camera = self.read("polstation-camera-preview.service.in")
        self.assertNotIn("network-online.target", target)
        self.assertNotIn("network-online.target", camera)
        self.assertIn("After=local-fs.target network.target", camera)

    def test_camera_address_hook_reorders_after_dhcp(self):
        hook = (
            NETWORKMANAGER / "90-polstation-camera-address"
        ).read_text()
        self.assertIn("up|dhcp4-change", hook)
        self.assertIn("grep -v -q ' inet 169\\.254\\.'", hook)
        self.assertLess(
            hook.index("address delete 169.254.68.1/16"),
            hook.index("address add 169.254.68.1/16"),
        )

    def test_observation_recorder_owns_cameras_and_writes_only_data_and_state(self):
        recorder = self.read("polstation-observation-recorder.service.in")
        self.assertIn("User=polstation", recorder)
        self.assertIn("EnvironmentFile=/etc/polstation/vimbax.env", recorder)
        self.assertIn("polstation-observation-recorder", recorder)
        self.assertIn("Conflicts=polstation-camera-preview.service", recorder)
        self.assertIn(
            "ReadWritePaths=/var/lib/polstation/data /var/lib/polstation/state",
            recorder,
        )
        self.assertIn("TimeoutStopSec=150", recorder)
        self.assertNotIn("PartOf=polstation-preview.target", recorder)
        self.assertNotIn(
            "polstation-observation-recorder.service",
            self.read("polstation-preview.target"),
        )


if __name__ == "__main__":
    unittest.main()
