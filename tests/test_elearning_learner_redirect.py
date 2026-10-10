"""Expired partner learner sessions return to their own access page."""
import app as host
import elearning_orders as learning

from test_elearning_orders import submit, run
from test_manuals_shop import shop


def test_partner_exam_without_session_returns_to_centre_access_page(shop):
    order = submit(shop, free=True)
    run(order)
    token = learning.access_token(host, order, order["learners"][0])
    learner = host.app.test_client()

    response = learner.get(f"/espace/{token}/elearning/exams/module-01")

    assert response.status_code == 302
    assert response.location == f"/apprendre/{token}"
    landing = learner.get(response.location)
    assert landing.status_code == 200
    assert "Centre de formation test" in landing.text
    assert 'name="birth"' not in landing.text


def test_historical_trainee_exam_keeps_its_existing_login(shop):
    learner = host.app.test_client()

    response = learner.get("/espace/historical-token/elearning/exams/module-01")

    assert response.status_code == 302
    assert response.location == "/espace/historical-token/login"
