"""Exercise a real first HTTP request against the gateway and a disposable origin."""
import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import sleep

PAGE = Path("index.html").read_bytes()
HOST = "www.integraleconnect.com"
state = {"status": 502, "requests": []}
class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        self.answer()
    def do_POST(self):
        self.answer()
    def answer(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        state["requests"].append((self.command, self.path, self.headers.get("Host"), body))
        self.send_response(state["status"])
        self.send_header("Content-Type", "text/plain")
        if state["status"] == 302:
            self.send_header("Location", "/login?next=/admin/partners")
        if state["status"] == 200:
            self.send_header("Set-Cookie", "session=test-only; Secure; HttpOnly")
        self.end_headers()
        self.wfile.write(b"origin")
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 19077), Origin)
Thread(target=server.serve_forever, daemon=True).start()
def request(path="/admin/partners?filter=active", method="GET", accept="text/html", body=None, host=HOST, dest="document"):
    conn = http.client.HTTPConnection("127.0.0.1", 19078, timeout=6)
    headers = {"Host": host, "Accept": accept}
    if dest is not None:
        headers["Sec-Fetch-Dest"] = dest
    conn.request(method, path, body, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, response.headers, data

for attempt in range(50):
    try:
        assert request(host="unconfigured.example")[0] == 404
        break
    except ConnectionRefusedError:
        if attempt == 49: raise
        sleep(.2)

for failure in (502, 503, 504):
    state["status"] = failure
    for dest in ("document", None):
        status, headers, data = request(dest=dest)
        assert status == 503 and data == PAGE, (failure, status, data[:100])
        assert headers["Retry-After"] == "12" and "no-store" in headers["Cache-Control"]
    assert request("/healthz")[0::2] == (failure, b"origin")
    assert request("/api/payments")[0::2] == (failure, b"origin")
    assert request(accept="application/json", dest="empty")[0::2] == (failure, b"origin")
    count = len(state["requests"])
    assert request(method="POST", body=b"unique")[0::2] == (failure, b"origin")
    assert state["requests"][count:] == [("POST", "/admin/partners?filter=active", HOST, b"unique")]
for other in (401, 403, 404, 500):
    state["status"] = other
    assert request()[0::2] == (other, b"origin")
state["status"] = 302
assert request()[1]["Location"] == "/login?next=/admin/partners"
state["status"] = 200
assert request()[1]["Set-Cookie"] == "session=test-only; Secure; HttpOnly"
assert request("/healthz")[0::2] == (200, b"origin")
assert request()[0::2] == (200, b"origin")
assert state["requests"][-1][1] == "/admin/partners?filter=active"
server.shutdown()
server.server_close()
status, headers, data = request()
assert status == 503 and data == PAGE, (status, data[:150])
assert request("/healthz")[0] in (502, 503, 504)
print("PASS first visit 502/503/504, offline origin, restored navigation, JSON, health, POST once, cookie and redirect")
