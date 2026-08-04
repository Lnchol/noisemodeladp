"""Source-labelled v6.3 aircraft presets for component-physics screening.

Only values supported by the linked first-party sources are declared
``supplied``. Wing area and high-lift geometry remain explicit estimates where
the public source set does not provide the component-ready quantity.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetSource:
    title: str
    url: str
    fields: tuple[str, ...]


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

    @property
    def estimated_wing_area_m2(self) -> float:
        """Transparent AR=9 estimate; not presented as published geometry."""
        return self.wing_span_m ** 2 / 9.0


PHYSICS_PRESETS = {
    "A320-270N": PhysicsPreset(
        key="A320-270N",
        label="A320-270N · PW1120G-JM",
        anp_id="A320-270N",
        description="Airbus A320-270N / PW1120G-JM",
        n_engines=2,
        max_thrust_lbf=26700.0,
        mtow_lb=174165.0,
        mlw_lb=148591.0,
        noise_chapter=14,
        bpr=12.0,
        wing_span_m=35.80,
        fan_diameter_m=81.0 * 0.0254,
        fan_blades=24,  # unavailable publicly; retained model estimate
        nose_wheel_count=2,
        main_wheel_count=4,
        nose_wheel_diameter_m=0.762,
        main_wheel_diameter_m=1.1684,
        sources=(
            PresetSource(
                "Airbus A320neo product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/"
                "a320-family/a320neo",
                ("wing_span_m",)),
            PresetSource(
                "Pratt & Whitney GTF engine fast facts",
                "https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/"
                "collateral/documents/commercial-engines/gtf-fast-facts.pdf",
                ("bpr", "fan_diameter_m")),
            PresetSource(
                "Airbus A320 Aircraft Characteristics",
                "https://aircraft.airbus.com/sites/g/files/jlcbta126/files/"
                "2024-06/AC_A320_0624.pdf",
                ("nose_wheel_count", "main_wheel_count",
                 "nose_wheel_diameter_m", "main_wheel_diameter_m")),
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
        nose_wheel_diameter_m=0.90,  # visible estimate
        main_wheel_diameter_m=1.40,  # visible estimate
        sources=(
            PresetSource(
                "Airbus A350-1000 product specifications",
                "https://www.aircraft.airbus.com/en/aircraft/a350/a350-1000",
                ("wing_span_m",)),
            PresetSource(
                "Rolls-Royce Trent XWB technical data",
                "https://www.rolls-royce.com/~/media/Files/R/Rolls-Royce/"
                "documents/civil-aerospace-downloads/High-Res-posters/"
                "High-Res-poster_Trent-XWB.pdf",
                ("bpr", "fan_diameter_m", "fan_blades")),
            PresetSource(
                "Airbus A350-1000 certification overview",
                "https://www.airbus.com/en/newsroom/news/2017-11-the-"
                "a350-1000-is-certified-for-airline-service",
                ("main_wheel_count",)),
            PresetSource(
                "Airbus A350 Aircraft Characteristics",
                "https://aircraft.airbus.com/sites/g/files/jlcbta126/files/"
                "2024-12/AC_A350_1224.pdf",
                ("nose_wheel_count",)),
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
        nose_wheel_diameter_m=1.10,  # visible estimate
        main_wheel_diameter_m=1.40,  # visible estimate
        sources=(
            PresetSource(
                "Boeing 777 design and characteristics",
                "https://www.boeing.com/Commercial/777/design-highlights",
                ("wing_span_m",)),
            PresetSource(
                "Boeing 777-300ER Airport Planning Characteristics",
                "https://www.boeing.com/content/dam/boeing/v2/airports/"
                "acaps/777-200LR-300ER-F_Rev_G.pdf",
                ("nose_wheel_count", "main_wheel_count")),
            PresetSource(
                "GE Aerospace GE90 history",
                "https://www.geaerospace.com/company/about-us/history",
                ("bpr", "fan_diameter_m")),
            PresetSource(
                "GE Aerospace composite fan blade history",
                "https://www.geaerospace.com/news/ko/press-releases/"
                "commercial-engines/ges-composite-fan-blade-revolution-"
                "turns-20-years-old",
                ("fan_blades",)),
        ),
    ),
}


def preset_labels() -> dict[str, str]:
    return {preset.label: key for key, preset in PHYSICS_PRESETS.items()}
