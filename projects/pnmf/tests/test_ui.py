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


def test_predict_et():
    at = AppTest.from_file(APP).run(timeout=120)
    at.selectbox(key="f_model").set_value("et")
    next(b for b in at.button if b.label == "Predict").click()
    at.run(timeout=300)
    assert not at.exception
    assert "prediction" in at.session_state
    assert len(at.session_state["prediction"].tables) == 8
