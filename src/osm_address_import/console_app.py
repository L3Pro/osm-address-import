"""Local-only browser for approved historical OSM sandbox audit reports."""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path

from flask import Flask, Response, abort, render_template, request

from osm_address_import.brazil_reports import COUNT_COLUMNS, METRICS, ReportError
from osm_address_import.console_data import ReportRepository, shown


def create_app(reports_root="reports/runs", *, development_mode=False):
    if development_mode and os.getenv("OSM_CONSOLE_ENV") == "production":
        raise ValueError("development bypass is forbidden in production")
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["REPORTS"] = ReportRepository(reports_root)
    app.config["DEV_MODE"] = development_mode
    app.jinja_env.filters["shown"] = shown
    app.jinja_env.filters["count"] = lambda value: "Unknown" if value is None else f"{value:,}"

    @app.before_request
    def require_access():
        # JWT authentication is intentionally deferred. No proxy identity header is trusted.
        try:
            loopback = ipaddress.ip_address(request.remote_addr or "").is_loopback
        except ValueError:
            loopback = False
        if (not app.config["DEV_MODE"] or not loopback or
                request.headers.get("X-Forwarded-For") or request.headers.get("CF-Connecting-IP")):
            abort(403)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        return response

    @app.get("/")
    def index():
        return render_template("console/index.html", inventory=app.config["REPORTS"].inventory())

    @app.get("/cities/<slug>")
    def city(slug):
        area = app.config["REPORTS"].city(slug)
        if area is None:
            abort(404)
        return render_template("console/city.html", area=area, metrics=METRICS, columns=COUNT_COLUMNS)

    @app.get("/runs/<run_id>")
    def run(run_id):
        data = app.config["REPORTS"].run(run_id)
        if data is None:
            abort(404)
        return render_template("console/run.html", run=data, run_id=run_id)

    @app.get("/reports/<run_id>/<stem>.<extension>")
    def artifact(run_id, stem, extension):
        try:
            content = app.config["REPORTS"].artifact(run_id, stem, extension)
        except (ReportError, OSError, UnicodeError):
            abort(404)
        mimetype = "application/json" if extension == "json" else "text/plain"
        disposition = "attachment" if request.args.get("download") == "1" else "inline"
        response = Response(content, mimetype=mimetype)
        response.headers["Content-Disposition"] = f'{disposition}; filename="{stem}.{extension}"'
        return response

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reports-root", default=os.getenv("OSM_CONSOLE_REPORT_ROOT", "reports/runs"))
    args = parser.parse_args()
    if args.host != "127.0.0.1" or os.getenv("OSM_CONSOLE_DEV_MODE") != "1" or os.getenv("OSM_CONSOLE_ENV", "development") != "development":
        parser.error("local mode requires OSM_CONSOLE_DEV_MODE=1, development environment, and 127.0.0.1 binding")
    app = create_app(Path(args.reports_root), development_mode=True)
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
