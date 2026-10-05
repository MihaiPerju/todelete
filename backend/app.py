"""Minimal HTTP server that tests DB connectivity.

Endpoints:
  GET  /        — fetch the 20 most recent rows (no insert)
  POST /        — insert a row with an optional {"message": "..."} body, return updated rows
  GET  /healthz — liveness check
"""

import http.server
import json
import os
import traceback

import psycopg2
import psycopg2.extras


def db_connect():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
        sslmode=os.environ.get("POSTGRES_SSL_MODE", "require"),
        connect_timeout=5,
    )


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pg_probe_hits (
            id       SERIAL PRIMARY KEY,
            message  TEXT,
            hit_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def fetch_rows(cur):
    cur.execute("SELECT COUNT(*) AS total FROM pg_probe_hits")
    total = cur.fetchone()["total"]
    cur.execute(
        "SELECT id, message, hit_at::text FROM pg_probe_hits ORDER BY id DESC LIMIT 20"
    )
    rows = [dict(r) for r in cur.fetchall()]
    return {"total_hits": total, "rows": rows}


def get_records():
    with db_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            ensure_table(cur)
            result = fetch_rows(cur)
        conn.commit()
    return result


def insert_record(message: str | None):
    with db_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            ensure_table(cur)
            cur.execute(
                "INSERT INTO pg_probe_hits (message) VALUES (%s)",
                (message or None,),
            )
            result = fetch_rows(cur)
        conn.commit()
    return result


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"ok")
            return
        try:
            self._json(200, get_records())
        except Exception:
            self._json(500, {"error": traceback.format_exc()})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(body or b"{}")
            message = payload.get("message", "")
            self._json(200, insert_record(message))
        except Exception:
            self._json(500, {"error": traceback.format_exc()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    print(f"pg-probe listening on :{port}", flush=True)
    http.server.HTTPServer(("", port), Handler).serve_forever()
