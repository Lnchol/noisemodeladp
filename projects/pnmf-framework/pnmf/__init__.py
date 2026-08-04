"""
PNMF - Parametric Noise Modeling Framework for Future Aircraft Concepts
=======================================================================

TU Darmstadt / FSR Advanced Design Project.

Maps parametric aircraft definitions (geometry, propulsion, configuration
states) onto NPD-equivalent noise tables that the FSR / Doc 29-style noise
assessment tool consumes, using the EASA ANP database as ground truth.

Public API
----------
ANPDatabase        : loader/joiner for the EASA ANP CSV database
ParametricAircraft : the parametric aircraft definition (the framework input)
NPDTable           : an NPD curve set with Doc 29 interpolation (the output)
SurrogateNPDModel  : data-driven metamodel trained on the ANP population
PhysicsNPDModel    : independent component-source physics workflow
OperationalProfile : approach/departure procedure -> flight segments
"""
from .anp import ANPDatabase
from .core import ParametricAircraft
from .core import NPDTable, STANDARD_DISTANCES_FT
from .models import SurrogateNPDModel
from .operations import OperationalProfile
from .operations import DepartureSynthesizer
from .physics import (
    AirframePhysicalInputs,
    AtmosphericPhysicalInputs,
    EnginePhysicalInputs,
    EventDiagnostics,
    FlightTrajectoryInputs,
    PhysicalInput,
    PhysicsDesign,
    PhysicsNPDModel,
)
from .api import NoisePredictor, NoisePrediction

__all__ = [
    "ANPDatabase",
    "ParametricAircraft",
    "NPDTable",
    "STANDARD_DISTANCES_FT",
    "SurrogateNPDModel",
    "OperationalProfile",
    "DepartureSynthesizer",
    "PhysicsNPDModel",
    "PhysicsDesign",
    "PhysicalInput",
    "EnginePhysicalInputs",
    "AirframePhysicalInputs",
    "AtmosphericPhysicalInputs",
    "FlightTrajectoryInputs",
    "EventDiagnostics",
    "NoisePredictor",
    "NoisePrediction",
]
__version__ = "0.3.0"
