"""Keep the diagnostic systemd boundary aligned with the commissioned design."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy/systemd"


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


if __name__ == "__main__":
    unittest.main()
