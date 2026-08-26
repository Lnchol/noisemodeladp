"""Source-labelled trainable-aircraft presets for component-physics screening.

Only values labelled ``supplied`` have a linked source in the preset.  Numeric
defaults labelled ``estimated`` remain editable screening assumptions; absent
component decks are deliberately recorded as ``unavailable``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias


ProvenanceStatus: TypeAlias = Literal["supplied", "estimated", "unavailable"]


@dataclass(frozen=True)
class PresetSource:
    title: str
    url: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class FieldProvenance:
    field: str
    status: ProvenanceStatus


@dataclass(frozen=True)
class PhysicsPreset:
    key: str
    label: str
    anp_id: str
    description: str
    n_engines: int
    max_thrust_lbf: float
    mtow_lb: float
    mlw_lb: float
    noise_chapter: int
    bpr: float
    wing_span_m: float
    fan_diameter_m: float
    fan_blades: int
    nose_wheel_count: int
    main_wheel_count: int
    nose_wheel_diameter_m: float
    main_wheel_diameter_m: float
    sources: tuple[PresetSource, ...]
    provenance: tuple[FieldProvenance, ...] = ()

    @property
    def estimated_wing_area_m2(self) -> float:
        """Transparent AR=9 estimate; not presented as published geometry."""
        return self.wing_span_m ** 2 / 9.0


_ANP_FIELDS: Final = (
    "n_engines",
    "max_thrust_lbf",
    "mtow_lb",
    "mlw_lb",
    "noise_chapter",
)
_UNAVAILABLE_COMPONENT_DECKS: Final = (
    "engine_component_deck",
    "high_lift_geometry",
)
_ANP_V63_SOURCE: Final = PresetSource(
    "EASA ANP v6.3 aircraft data",
    "https://www.easa.europa.eu/en/domains/environment/"
    "policy-support-and-research/aircraft-noise-and-performance-anp-data",
    _ANP_FIELDS,
)


def _provenance(
    supplied: tuple[str, ...],
    estimated: tuple[str, ...],
    unavailable: tuple[str, ...] = _UNAVAILABLE_COMPONENT_DECKS,
) -> tuple[FieldProvenance, ...]:
    return (
        *(FieldProvenance(field, "supplied") for field in supplied),
        *(FieldProvenance(field, "estimated") for field in estimated),
        *(FieldProvenance(field, "unavailable") for field in unavailable),
    )


# noqa: SIZE_OK - this is one auditable static data registry; splitting it would
# hide each aircraft's values from its field-level sources and provenance.
PHYSICS_PRESETS = {
    "A320-270N": PhysicsPreset(
        key="A320-270N",
        label="A320-270N · PW1100G-JM",
        anp_id="A320-270N",
        description="Airbus A320-270N / PW1100G-JM",
        n_engines=2,
        max_thrust_lbf=26700.0,
        mtow_lb=174165.0,
        mlw_lb=148591.0,
        noise_chapter=14,
        bpr=12.0,
        wing_span_m=35.80,
        fan_diameter_m=81.0 * 0.0254,
        fan_blades=24,
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.762,
        main_wheel_diameter_m=1.1684,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Airbus A320neo product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/a320-family/a320neo",
                ("wing_span_m",),
            ),
            PresetSource(
                "Pratt & Whitney GTF engine fast facts",
                "https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/"
                "collateral/documents/commercial-engines/gtf-fast-facts.pdf",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "A321-270N": PhysicsPreset(
        key="A321-270N",
        label="A321-270N · PW1100G-JM",
        anp_id="A321-270N",
        description="Airbus A321-270N / PW1100G-JM",
        n_engines=2,
        max_thrust_lbf=33110.0,
        mtow_lb=213848.0,
        mlw_lb=174606.0,
        noise_chapter=14,
        bpr=12.0,
        wing_span_m=35.80,
        fan_diameter_m=81.0 * 0.0254,
        fan_blades=24,
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.762,
        main_wheel_diameter_m=1.1684,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Airbus A321neo product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/a320-family/a321neo",
                ("wing_span_m",),
            ),
            PresetSource(
                "Pratt & Whitney GTF engine fast facts",
                "https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/"
                "collateral/documents/commercial-engines/gtf-fast-facts.pdf",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "A330-743L": PhysicsPreset(
        key="A330-743L",
        label="A330-743L · Trent 772B",
        anp_id="A330-743L",
        description="Airbus A330-743L / RR Trent 772B",
        n_engines=2,
        max_thrust_lbf=71100.0,
        mtow_lb=500449.0,
        mlw_lb=412264.0,
        noise_chapter=14,
        bpr=5.1,
        wing_span_m=60.30,
        fan_diameter_m=97.5 * 0.0254,
        fan_blades=26,
        nose_wheel_count=2,
        main_wheel_count=8,
        nose_wheel_diameter_m=0.90,
        main_wheel_diameter_m=1.22,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Airbus A330 product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/a330-family/a330-300",
                ("wing_span_m",),
            ),
            PresetSource(
                "Rolls-Royce Trent 700 engine family",
                "https://www.rolls-royce.com/products-and-services/"
                "civil-aerospace/widebody/trent-700.aspx",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "A350-1041": PhysicsPreset(
        key="A350-1041",
        label="A350-1041 · Trent XWB-97",
        anp_id="A350-1041",
        description="Airbus A350-1041 / RR Trent XWB-97",
        n_engines=2,
        max_thrust_lbf=97000.0,
        mtow_lb=696661.0,
        mlw_lb=520291.0,
        noise_chapter=14,
        bpr=9.6,
        wing_span_m=64.75,
        fan_diameter_m=118.0 * 0.0254,
        fan_blades=22,
        nose_wheel_count=2,
        main_wheel_count=12,
        nose_wheel_diameter_m=0.90,
        main_wheel_diameter_m=1.40,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Airbus A350-1000 product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/a350/a350-1000",
                ("wing_span_m",),
            ),
            PresetSource(
                "Rolls-Royce Trent XWB technical data",
                "https://www.rolls-royce.com/~/media/Files/R/Rolls-Royce/"
                "documents/civil-aerospace-downloads/High-Res-posters/"
                "High-Res-poster_Trent-XWB.pdf",
                ("bpr", "fan_diameter_m", "fan_blades"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m", "fan_blades"),
            ("nose_wheel_count", "main_wheel_count", "nose_wheel_diameter_m",
             "main_wheel_diameter_m"),
        ),
    ),
    "747400RN": PhysicsPreset(
        key="747400RN",
        label="747-400F · PW4062A",
        anp_id="747400RN",
        description="Boeing 747400RN / PW4062A",
        n_engines=4,
        max_thrust_lbf=59708.0,
        mtow_lb=875000.0,
        mlw_lb=652000.0,
        noise_chapter=3,
        bpr=5.8,
        wing_span_m=64.44,
        fan_diameter_m=94.0 * 0.0254,
        fan_blades=38,
        nose_wheel_count=2,
        main_wheel_count=16,
        nose_wheel_diameter_m=1.10,
        main_wheel_diameter_m=1.27,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Boeing 747 airport planning characteristics",
                "https://www.boeing.com/content/dam/boeing/v2/airports/"
                "acaps/747_4.pdf",
                ("wing_span_m",),
            ),
            PresetSource(
                "Pratt & Whitney PW4000 engine family",
                "https://www.prattwhitney.com/en/products-and-services/"
                "products/commercial-engines/pw4000",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "7673ER": PhysicsPreset(
        key="7673ER",
        label="767-300ER · CF6-80C2B6F",
        anp_id="7673ER",
        description="Boeing 767-300ER / CF6-80C2B6F",
        n_engines=2,
        max_thrust_lbf=61500.0,
        mtow_lb=412000.0,
        mlw_lb=320000.0,
        noise_chapter=4,
        bpr=5.1,
        wing_span_m=47.57,
        fan_diameter_m=93.0 * 0.0254,
        fan_blades=38,
        nose_wheel_count=2,
        main_wheel_count=8,
        nose_wheel_diameter_m=0.90,
        main_wheel_diameter_m=1.22,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Boeing 767 airport planning characteristics",
                "https://www.boeing.com/content/dam/boeing/v2/airports/"
                "acaps/767.pdf",
                ("wing_span_m",),
            ),
            PresetSource(
                "GE Aerospace CF6 engine family",
                "https://www.geaerospace.com/commercial/engines/cf6",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "7879": PhysicsPreset(
        key="7879",
        label="787-9 · GEnx-1B76A",
        anp_id="7879",
        description="Boeing 787-9 / GEnx-1B76A",
        n_engines=2,
        max_thrust_lbf=76000.0,
        mtow_lb=560000.0,
        mlw_lb=425000.0,
        noise_chapter=4,
        bpr=9.0,
        wing_span_m=60.12,
        fan_diameter_m=111.0 * 0.0254,
        fan_blades=18,
        nose_wheel_count=2,
        main_wheel_count=8,
        nose_wheel_diameter_m=0.90,
        main_wheel_diameter_m=1.22,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Boeing 787 airport planning characteristics",
                "https://www.boeing.com/content/dam/boeing/v2/airports/"
                "acaps/787.pdf",
                ("wing_span_m",),
            ),
            PresetSource(
                "GE Aerospace GEnx engine family",
                "https://www.geaerospace.com/commercial/engines/genx",
                ("bpr", "fan_diameter_m", "fan_blades"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m", "fan_blades"),
            ("nose_wheel_count", "main_wheel_count", "nose_wheel_diameter_m",
             "main_wheel_diameter_m"),
        ),
    ),
    "7773ER": PhysicsPreset(
        key="7773ER",
        label="777-300ER · GE90-115B",
        anp_id="7773ER",
        description="Boeing 777-300ER / GE90-115B",
        n_engines=2,
        max_thrust_lbf=115000.0,
        mtow_lb=775000.0,
        mlw_lb=554000.0,
        noise_chapter=4,
        bpr=9.0,
        wing_span_m=64.80,
        fan_diameter_m=128.0 * 0.0254,
        fan_blades=22,
        nose_wheel_count=2,
        main_wheel_count=12,
        nose_wheel_diameter_m=1.10,
        main_wheel_diameter_m=1.40,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Boeing 777 airport planning characteristics",
                "https://www.boeing.com/content/dam/boeing/v2/airports/"
                "acaps/777-200LR-300ER-F_Rev_G.pdf",
                ("wing_span_m",),
            ),
            PresetSource(
                "GE Aerospace GE90 engine family",
                "https://www.geaerospace.com/commercial/engines/ge90",
                ("bpr", "fan_diameter_m", "fan_blades"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m", "fan_blades"),
            ("nose_wheel_count", "main_wheel_count", "nose_wheel_diameter_m",
             "main_wheel_diameter_m"),
        ),
    ),
    "ERJ190-300": PhysicsPreset(
        key="ERJ190-300",
        label="E190-E2 · PW1900G",
        anp_id="ERJ190-300",
        description="ERJ 190-300 / PW1900G",
        n_engines=2,
        max_thrust_lbf=21300.0,
        mtow_lb=124341.0,
        mlw_lb=108137.0,
        noise_chapter=14,
        bpr=12.0,
        wing_span_m=28.72,
        fan_diameter_m=73.0 * 0.0254,
        fan_blades=20,
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.66,
        main_wheel_diameter_m=0.97,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Embraer E190-E2 product specifications",
                "https://www.embraercommercialaviation.com/commercial-jets/e190-e2/",
                ("wing_span_m",),
            ),
            PresetSource(
                "Pratt & Whitney GTF engine fast facts",
                "https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/"
                "collateral/documents/commercial-engines/gtf-fast-facts.pdf",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "ERJ190-400": PhysicsPreset(
        key="ERJ190-400",
        label="E195-E2 · PW1900G",
        anp_id="ERJ190-400",
        description="ERJ 190-400 / PW1900G",
        n_engines=2,
        max_thrust_lbf=21300.0,
        mtow_lb=135584.0,
        mlw_lb=119049.0,
        noise_chapter=14,
        bpr=12.0,
        wing_span_m=28.72,
        fan_diameter_m=73.0 * 0.0254,
        fan_blades=20,
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.66,
        main_wheel_diameter_m=0.97,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Embraer E195-E2 product specifications",
                "https://www.embraercommercialaviation.com/commercial-jets/e195-e2/",
                ("wing_span_m",),
            ),
            PresetSource(
                "Pratt & Whitney GTF engine fast facts",
                "https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/"
                "collateral/documents/commercial-engines/gtf-fast-facts.pdf",
                ("bpr", "fan_diameter_m"),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("bpr", "wing_span_m", "fan_diameter_m"),
            ("fan_blades", "nose_wheel_count", "main_wheel_count",
             "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
    "FAL900EX": PhysicsPreset(
        key="FAL900EX",
        label="Falcon 900EX · TFE731-60",
        anp_id="FAL900EX",
        description="Dassault FAL900EX / TFE731-60",
        n_engines=3,
        max_thrust_lbf=5000.0,
        mtow_lb=49000.0,
        mlw_lb=44500.0,
        noise_chapter=4,
        bpr=2.8,
        wing_span_m=19.33,
        fan_diameter_m=0.79,
        fan_blades=22,
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.56,
        main_wheel_diameter_m=0.84,
        sources=(
            _ANP_V63_SOURCE,
            PresetSource(
                "Dassault Falcon 900EX specifications",
                "https://www.dassaultfalcon.com/aircraft/falcon-900ex",
                ("wing_span_m",),
            ),
        ),
        provenance=_provenance(
            _ANP_FIELDS + ("wing_span_m",),
            ("bpr", "fan_diameter_m", "fan_blades", "nose_wheel_count",
             "main_wheel_count", "nose_wheel_diameter_m", "main_wheel_diameter_m"),
        ),
    ),
}


def preset_labels() -> dict[str, str]:
    return {preset.label: key for key, preset in PHYSICS_PRESETS.items()}
