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


def _assert_methodology_panel(at):
    assert any(item.label == "Method, sources, and limitations"
               for item in at.expander)
    markdown = [item.value for item in at.markdown]
    for heading in ("**Inputs/source**", "**Transformation or method**",
                    "**Output**", "**Evidence boundary**"):
        assert any(heading in value for value in markdown)
    assert any("easa.europa.eu" in value.lower() for value in markdown)
    assert any("ecac-ceac.org" in value.lower() for value in markdown)


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


@pytest.mark.parametrize(
    "page",
    ["Comparison", "Prediction results", "Operations"],
)
def test_empty_user_facing_pages_explain_their_method(page):
    at = AppTest.from_file(APP).run(timeout=120)
    at.radio(key="nav").set_value(page)
    at.run(timeout=120)
    assert not at.exception
    _assert_methodology_panel(at)


def test_fleet_validation_evidence_explains_fixed_routes_and_report():
    at = AppTest.from_file(APP).run(timeout=120)
    at.radio(key="nav").set_value("Fleet explorer")
    at.run(timeout=120)
    assert not at.exception
    _assert_methodology_panel(at)
    captions = [item.value for item in at.caption]
    assert any("Extra Trees" in value and "fixed production" in value
               for value in captions)
    assert any("Random Forest" in value and "validation challenger" in value
               for value in captions)
    assert any("Active methodology report" in value for value in captions)
    assert any("JET_MODEL_METHODOLOGY_AND_VALIDATION_REPORT.md" in item.value
               for item in at.markdown)


@pytest.mark.parametrize(
    "page",
    ["Aircraft Designer", "Comparison", "Prediction results", "Operations",
     "Fleet explorer"],
)
def test_user_facing_pages_hide_internal_prediction_version_names(page):
    at = AppTest.from_file(APP).run(timeout=120)
    if page != "Aircraft Designer":
        at.radio(key="nav").set_value(page)
        at.run(timeout=120)
    visible = "\n".join(
        str(item.value)
        for element_type in (
            "caption", "markdown", "info", "success", "warning", "error",
            "subheader", "title",
        )
        for item in getattr(at, element_type)
    )
    assert "Jet-v2" not in visible
    assert "et-jet_merged-jet-v2" not in visible


def test_designer_starts_with_generic_aircraft_inputs():
    at = AppTest.from_file(APP).run(timeout=120)
    assert at.session_state["f_name"] == "New aircraft"
    assert at.session_state["f_engine_type"] == "Jet"
    assert at.session_state["f_n_engines"] == 2
    assert all("Load preset" not in button.label for button in at.button)
    assert at.session_state["f_analysis_approach"] == "Compare learned + physics"
    assert "Physics cross-check" not in at.radio(key="nav").options
    assert not any(widget.key in {"f_model", "f_training_scope"}
                   for widget in at.selectbox)


def test_predict_et():
    at = AppTest.from_file(APP).run(timeout=120)
    next(b for b in at.button
         if b.label == "Run learned model and prepare comparison").click()
    at.run(timeout=300)
    assert not at.exception
    assert "prediction" in at.session_state
    assert len(at.session_state["prediction"].tables) == 8
    assert at.session_state["prediction"].metadata["training_population"] == "jet_merged"
    assert at.session_state["prediction"].metadata["learner"] == "et"
    assert at.session_state["pred_meta"]["model_identity"] == "et-jet_merged-jet-v2"
    learned_log = at.session_state["calculation_logs"]["learned"]
    assert learned_log["state"] == "complete"
    assert sum("MODEL TABLE" in line
               for line in learned_log["entries"]) == 8
    assert any("POWER GRID" in line for line in learned_log["entries"])


def test_results_exposes_adjustable_thrust_curve():
    at = AppTest.from_file(APP).run(timeout=120)
    next(b for b in at.button
         if b.label == "Run learned model and prepare comparison").click()
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


def test_component_physics_ui_runs_event_and_exposes_diagnostics():
    at = AppTest.from_file(APP).run(timeout=120)
    next(b for b in at.button
         if b.label == "Run learned model and prepare comparison").click()
    at.run(timeout=300)

    assert any(i.key == "phys_thrust_imperial" for i in at.number_input)
    assert any(i.key == "phys_distance_imperial" for i in at.number_input)
    next(b for b in at.button if b.label == "Run component physics").click()
    at.run(timeout=300)

    assert not at.exception
    result = at.session_state["physics_result"]
    diagnostics = result["diagnostics"]
    assert diagnostics.sel_db > diagnostics.lamax_db
    assert set(result["tables"]) == {"SEL", "LAmax"}
    assert result["tables"]["SEL"].L.shape == (1, 10)
    assert "airframe" in diagnostics.source_status
    assert any(m.label == "Physics SEL" for m in at.metric)
    physics_log = at.session_state["calculation_logs"]["physics"]
    assert physics_log["state"] == "complete"
    assert any("SOURCES" in line for line in physics_log["entries"])
    assert any("ENERGY SUM" in line for line in physics_log["entries"])
    assert any("EVENT METRIC" in line for line in physics_log["entries"])
    assert sum("PHYSICS NPD" in line
               for line in physics_log["entries"]) == 2


def test_component_physics_ui_applies_source_labelled_v63_preset():
    at = AppTest.from_file(APP).run(timeout=120)
    at.selectbox(key="f_aircraft_preset").set_value("A350-1041")
    next(b for b in at.button
         if b.label == "Apply to both models").click()
    at.run(timeout=120)

    assert not at.exception
    assert at.session_state["phys_active_preset"] == "A350-1041"
    assert at.session_state["phys_bpr"] == pytest.approx(9.6)
    assert at.session_state["phys_wing_span"] == pytest.approx(64.75)
    assert at.session_state["phys_main_wheels"] == 12
    assert at.session_state["phys_fan_diameter_basic"] == pytest.approx(
        118.0 * 0.0254)
    assert at.session_state["f_name"].startswith("Airbus A350-1041")
    assert at.session_state["f_bpr"] == pytest.approx(9.6)
    assert any("Shared aircraft" in message.value for message in at.success)

    next(b for b in at.button
         if b.label == "Run learned model and prepare comparison").click()
    at.run(timeout=300)

    next(b for b in at.button if b.label == "Run component physics").click()
    at.run(timeout=300)
    result = at.session_state["physics_result"]
    assert result["preset"] == "A350-1041"
    assert result["aircraft"].startswith("Airbus A350-1041")
    assert set(result["learned_tables"]) == {"SEL", "LAmax"}
    assert all(table is not None for table in result["learned_tables"].values())
    assert result["diagnostics"].input_status["span_m"].source == "supplied"
    assert result["diagnostics"].input_status["wing_area_m2"].source == "estimated"


def test_component_physics_only_mode_hides_learned_overlay():
    at = AppTest.from_file(APP).run(timeout=120)
    at.radio(key="f_analysis_approach").set_value("Component physics only")
    at.run(timeout=120)
    next(b for b in at.button
         if b.label == "Prepare component physics").click()
    at.run(timeout=300)
    next(b for b in at.button if b.label == "Run component physics").click()
    at.run(timeout=300)

    result = at.session_state["physics_result"]
    assert result["compare_learned"] is False
    assert all(table is None for table in result["learned_tables"].values())
    assert not any("Physics −" in metric.label for metric in at.metric)
