"""Point d'entrée Gunicorn avec les extensions isolées de Gestion Stagiaires."""

import app as legacy_app

from admin_trainee_wedof_refresh import register_admin_trainee_wedof_refresh
from bts_workspace import register_bts_workspace
from crm_cnaps_tracking_api import register_crm_cnaps_tracking_api
from wedof_invoice_reconciliation import register_wedof_invoice_reconciliation


app = legacy_app.app
register_admin_trainee_wedof_refresh(legacy_app)
register_wedof_invoice_reconciliation(legacy_app)
register_bts_workspace(legacy_app)
register_crm_cnaps_tracking_api(
    app,
    fetch_tracking_requests=legacy_app.fetch_cnapsv3_tracking_requests,
    fetch_public_annuaire=getattr(legacy_app, "fetch_cnaps_public_annuaire", None),
)
