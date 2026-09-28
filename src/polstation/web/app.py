"""Loopback-only, read-only status dashboard for access over an SSH tunnel."""
import argparse
import json
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit
from polstation.cameras.demo import DemoPreviewSource
from polstation.cameras.preview import FilePreviewSource
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from polstation.config import load_config
from polstation.health.status import read

PAGE = b"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Polstation status</title><h1>Polstation</h1>
<p>Scaffold mode: camera acquisition and sensor drivers are not implemented.</p>
<pre id="status">Loading status...</pre><script>
async function refresh() {try {
const response = await fetch('/api/status');
document.getElementById('status').textContent = JSON.stringify(await response.json(), null, 2);
} catch (_) {document.getElementById('status').textContent = 'Dashboard connection unavailable';}}
refresh(); setInterval(refresh, 5000);
</script></html>"""


def make_handler(config, preview_source=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlsplit(self.path)
            if request.path == "/":
                body = files("polstation.web").joinpath("static/dashboard.html").read_bytes() if preview_source else PAGE
                code, content_type = 200, "text/html; charset=utf-8"
            elif request.path in ("/static/dashboard.css", "/static/dashboard.js") and preview_source:
                name = request.path.rsplit("/", 1)[1]
                content_type = "text/css" if name.endswith(".css") else "text/javascript"
                code, body = 200, files("polstation.web").joinpath("static", name).read_bytes()
            elif request.path == "/api/previews" and preview_source:
                scenario = parse_qs(request.query).get("scenario", ["live"])[0]
                try:
                    code, body = 200, json.dumps(preview_source.snapshot(scenario)).encode()
                except ValueError as error:
                    code, body = 400, json.dumps({"error": str(error)}).encode()
                content_type = "application/json"
            elif self.path == "/api/status":
                status = read(config)
                code = 503 if status["stale"] or status["state"] != "scaffold_idle" else 200
                content_type, body = "application/json", json.dumps(status).encode()
            else:
                code, content_type, body = 404, "text/plain", b"Not found"
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--demo", action="store_true", help="Show simulated cameras; no hardware or scientific data writes")
    parser.add_argument("--hardware-preview", action="store_true", help="Read real-camera preview snapshots; never opens cameras")
    args = parser.parse_args()
    if args.demo and args.hardware_preview:
        parser.error("--demo and --hardware-preview are mutually exclusive")
    config = load_config(args.config)
    source = DemoPreviewSource(config["cameras"]) if args.demo else FilePreviewSource(config) if args.hardware_preview else None
    server = ThreadingHTTPServer((config["dashboard"]["host"], config["dashboard"]["port"]), make_handler(config, source))
    mode = "DEMO" if args.demo else "HARDWARE PREVIEW" if args.hardware_preview else "scaffold"
    print(f"Polstation {mode} dashboard: http://{config['dashboard']['host']}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
