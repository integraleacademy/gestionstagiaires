"""Point d'entrée Gunicorn avec l'API CNAPS dédiée au CRM."""

import app as legacy_app

from admin_trainee_wedof_refresh import register_admin_trainee_wedof_refresh
from crm_cnaps_tracking_api import register_crm_cnaps_tracking_api


app = legacy_app.app
register_admin_trainee_wedof_refresh(legacy_app)
register_crm_cnaps_tracking_api(
    app,
    fetch_tracking_requests=legacy_app.fetch_cnapsv3_tracking_requests,
    fetch_public_annuaire=getattr(legacy_app, "fetch_cnaps_public_annuaire", None),
)
