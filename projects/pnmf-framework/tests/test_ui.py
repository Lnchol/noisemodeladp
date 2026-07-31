"""Headless smoke tests for the Streamlit UI (pnmf_ui.py)."""
import os
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(
        os.path.dirname(__file__), os.pardir, "anp_data.sqlite")),
    reason="anp_data.sqlite not staged (run pnmf_cli.py datastore)")

APP = os.path.join(os.path.dirname(__file__), os.pardir, "pnmf_ui.py")


def test_ui_boots():
    at = AppTest.from_file(APP).run(timeout=120)
    assert not at.exception
    assert len(at.title) > 0
    assert "PNMF" in at.title[0].value


def test_fleet_explorer_renders():
    at = AppTest.from_file(APP).run(timeout=120)
    at.radio(key="nav").set_value("Fleet explorer")
    at.run(timeout=120)
    assert not at.exception
    assert len(at.dataframe) >= 1


def test_designer_starts_with_generic_aircraft_inputs():
    at = AppTest.from_file(APP).run(timeout=120)
    assert at.session_state["f_name"] == "New aircraft"
    assert at.session_state["f_engine_type"] == "Jet"
    assert at.session_state["f_n_engines"] == 2
    assert all("Load preset" not in button.label for button in at.button)


def test_predict_et():
    at = AppTest.from_file(APP).run(timeout=120)
    at.selectbox(key="f_model").set_value("et")
    next(b for b in at.button if b.label == "Predict").click()
    at.run(timeout=300)
    assert not at.exception
    assert "prediction" in at.session_state
    assert len(at.session_state["prediction"].tables) == 8


def test_results_exposes_adjustable_thrust_curve():
    at = AppTest.from_file(APP).run(timeout=120)
    next(b for b in at.button if b.label == "Predict").click()
    at.run(timeout=300)
    at.radio(key="nav").set_value("Prediction results")
    at.run(timeout=120)
    at.selectbox(key="res_metric").set_value("SEL")
    at.run(timeout=120)
    assert any("Reference noise levels" in caption.value for caption in at.caption)
    thrust = next(i for i in at.number_input
                  if i.key == "res_thrust_SEL_D_imperial")
    thrust.set_value(25000.0)
    at.run(timeout=120)
    assert at.session_state["res_thrust_SEL_D_imperial"] == 25000.0


def test_ui_exposes_separate_custom_power_grids():
    at = AppTest.from_file(APP).run(timeout=120)
    departure = next(i for i in at.text_input if i.key == "f_departure_powers")
    approach = next(i for i in at.text_input if i.key == "f_approach_powers")
    departure.set_value("18000, 24000")
    approach.set_value("2500, 4500")
    at.run(timeout=120)
    assert at.session_state["f_departure_powers"] == "18000, 24000"
    assert at.session_state["f_approach_powers"] == "2500, 4500"
