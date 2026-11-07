"""A tiny fake Spoolman for tests: serves GET /api/v1/spool on localhost."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def spool(sid, fid, name, material, color, location="Tim", remaining=500.0,
          archived=False, vendor="Elegoo", **filament_extra):
    filament = {"id": fid, "name": name, "material": material,
                "color_hex": color, "vendor": {"id": 1, "name": vendor}}
    filament.update(filament_extra)
    return {"id": sid, "filament": filament, "remaining_weight": remaining,
            "location": location, "archived": archived}


class FakeSpoolman:
    def __init__(self, spools=None):
        self.spools = spools or []
        self.hits = 0
        self.fail = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                if outer.fail or self.path != "/api/v1/spool":
                    self.send_response(500 if outer.fail else 404)
                    self.end_headers()
                    return
                body = json.dumps(outer.spools).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
