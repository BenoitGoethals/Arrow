#!/usr/bin/env python3
"""Webhook receiver for testing Octopus Deploy webhooks."""

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "0.0.0.0"
PORT = 8080


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] POST {self.path}")
        print(f"From: {self.client_address[0]}")

        for key, value in self.headers.items():
            if key.lower() not in ("host", "content-length", "connection"):
                print(f"  {key}: {value}")

        if body:
            try:
                payload = json.loads(body)
                print("Body:")
                print(json.dumps(payload, indent=2))
            except json.JSONDecodeError:
                print(f"Body (raw): {body.decode('utf-8', errors='replace')}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Webhook receiver is running.\n")

    def log_message(self, format, *args):
        pass  # suppress default access log noise


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = HTTPServer((HOST, port), WebhookHandler)
    print(f"Listening for webhooks on port {port}")
    print(f"Configure Octopus (192.168.0.240) to POST to http://<this-machine>:{port}/")
    print("Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
