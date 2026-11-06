"""Install the maintenance fallback without changing users' URLs or sessions."""

import os

from flask import request


PRODUCTION_SERVICE_ID = "srv-d5oss66id0rc73avvne0"
REGISTRATION_SCRIPT = (
    b'<script defer src="/static/maintenance-register.js?v=20261106-1"></script>'
)


def register_maintenance_recovery(app, *, enabled=None):
    if enabled is None:
        enabled = os.environ.get("RENDER_SERVICE_ID") == PRODUCTION_SERVICE_ID
    if not enabled or app.extensions.get("maintenance_recovery"):
        return
    app.extensions["maintenance_recovery"] = True

    @app.after_request
    def install_maintenance_recovery(response):
        # Full browser pages only. Never buffer files/streams or touch API data,
        # form submissions, redirects, or partial HTML returned to fetch().
        if (
            request.method != "GET"
            or response.status_code != 200
            or response.mimetype != "text/html"
            or response.direct_passthrough
            or response.is_streamed
            or response.headers.get("Content-Encoding")
            or response.headers.get("Content-Disposition")
            or request.headers.get("X-Requested-With")
        ):
            return response
        destination = request.headers.get("Sec-Fetch-Dest")
        if destination not in {None, "document", "iframe"}:
            return response
        if destination is None and "text/html" not in request.headers.get("Accept", ""):
            return response
        body = response.get_data()
        end = body.lower().rfind(b"</body>")
        if end < 0 or b"/static/maintenance-register.js" in body:
            return response
        response.set_data(body[:end] + REGISTRATION_SCRIPT + b"\n" + body[end:])
        for header in ("ETag", "Content-MD5", "Digest"):
            response.headers.pop(header, None)
        return response
