"""Gunicorn entry point for the production-mode console."""

from osm_address_import.console_app import create_production_app

app = create_production_app()
