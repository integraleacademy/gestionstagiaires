"""Point d'entrée Gunicorn avec les extensions isolées de Gestion Stagiaires."""

import app as legacy_app

from maintenance_recovery import register_maintenance_recovery

from bts_workspace import register_bts_workspace
from cnaps_notification_recovery import register_cnaps_notification_recovery
from crm_cnaps_tracking_api import register_crm_cnaps_tracking_api
from elearning_native.integration import register_native_elearning
from wedof_invoice_reconciliation import register_wedof_invoice_reconciliation
from maintenance_jobs import register_maintenance_jobs
from cpf_provider import register_wedof_guards
from cpf_provider_bridge import register_production_control


app = legacy_app.app
register_maintenance_recovery(app)
register_native_elearning(legacy_app)
register_wedof_invoice_reconciliation(legacy_app)
register_bts_workspace(legacy_app)
register_cnaps_notification_recovery(legacy_app)
register_crm_cnaps_tracking_api(
    app,
    fetch_tracking_requests=legacy_app.fetch_cnapsv3_tracking_requests,
    fetch_public_annuaire=getattr(legacy_app, "fetch_cnaps_public_annuaire", None),
)
register_production_control(legacy_app)
register_wedof_guards(app)
register_maintenance_jobs(legacy_app)

from cpf_provider import on_production_service, production_edof_ready
if on_production_service():
    from edof_readonly_test import register_edof_readonly_test
    from edof_server_test import register_edof_server_test
    if production_edof_ready():
        register_edof_readonly_test(legacy_app)
        register_edof_server_test(legacy_app)
    else:
        @app.get("/admin/integrale-edof")
        @legacy_app.admin_login_required
        def edof_handoff_pending():
            from flask import abort
            if not legacy_app._is_super_admin_session():
                abort(403)
            return "Intégrale EDOF est en cours de transfert depuis Test V2.", 503
