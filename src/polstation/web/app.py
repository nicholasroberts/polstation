"""Loopback-only, read-only status dashboard for access over an SSH tunnel."""
import argparse
import json
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


def make_handler(config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                code, content_type, body = 200, "text/html; charset=utf-8", PAGE
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
    config = load_config(parser.parse_args().config)
    server = ThreadingHTTPServer((config["dashboard"]["host"], config["dashboard"]["port"]), make_handler(config))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
