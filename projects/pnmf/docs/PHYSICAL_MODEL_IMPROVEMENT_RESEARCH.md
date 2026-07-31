# Research: improving the component-physics noise route

**Question.** Is there credible published work that supports improving PNMF's
component-source physical model?  **Answer:** yes.  The strongest evidence is
for improving *input fidelity and missing physical mechanisms*, rather than
retuning PNMF's four frozen A320-211 source anchors globally.

This note concerns the independent `PhysicsNPDModel` only.  It must remain
independent of ET/RF fitting, uses SI internally, and is a conceptual
SEL/LAmax screening model rather than a certification method.

## Current baseline and research implication

PNMF already evaluates separate Stone-style jet, Heidmann-style fan and
Fink-style airframe sources, propagates one-third-octave spectra, and makes
input provenance/fallbacks visible.  Its known gaps are installation,
shielding, ground/terrain, non-uniform atmosphere, detailed modern high-lift
geometry and fully validated engine decks.  The external evidence below
directly supports treating these as separable modules with their own data and
validation, not hiding them in the existing calibration constants.

## Evidence-backed upgrade priorities

| Priority | Improvement | Why it is supported | PNMF-safe first increment |
| --- | --- | --- | --- |
| 1 | Replace estimated propulsion inputs with a versioned engine deck | NASA's assessment of Stone's jet model over 258 cases confirms its speed, but a later flight comparison found that a 100--200 F exhaust-temperature difference can explain material differences. | Add an optional, provenance-labelled deck containing nozzle flow, temperature, pressure, diameter, fan map/RPM and operating point. Reject incomplete detailed-source inputs; keep today's named fallback. Validate component spectra before event levels. |
| 2 | Upgrade airframe sources for modern high-lift systems and interactions | NASA flight-test assessment on a 787-10 says present methods capture major features but calls out landing-gear-wake/flap interaction, slat-bracket noise, modern flap-side-edge mechanisms, and tapered/swept-wing trailing edges. | Extend typed geometry/configuration with flap architecture, sweep/taper, slat brackets, gear/flap relative position and local-flow state. Add each source/interaction behind an explicit availability gate and validate against component-resolved data. |
| 3 | Add a frequency- and geometry-dependent installation/scattering module | NASA system studies show that shielding, reflection and diffraction can materially change source predictions; an experiment reported up to 8 dB high-frequency jet shielding for one installation, while a newer Boeing-787 fan-scattering study incorporates source coherence and both tonal/broadband scattering. | Define a separate installation interface operating on component band spectra and source positions. Start with a bounded, validated conventional under-wing case; return `unavailable` for configurations outside that evidence base. Do not alter source-anchor calibration. |
| 4 | Make trajectory and propagation fidelity selectable | ECAC Doc 29 identifies the vertical profile of height, speed and engine power as key event-level inputs and calls segmentation best practice for general calculations. NASA's non-standard-atmosphere framework shows straight paths become inadequate at long range/shallow elevation angles. | Preserve current standard reference trajectory as the baseline. Add a segment trajectory input and an optional propagation mode whose meteorology, ground and validity range are recorded in diagnostics. Benchmark the unchanged baseline against ECAC reference cases first. |
| 5 | Establish component-to-system validation and uncertainty accounting | NASA's capability-assessment process compares predictions with measurements at component and system levels and quantifies both prediction and measurement uncertainty. Its hybrid-wing-body uncertainty work explicitly updates element uncertainty when methods or validation data improve. | Add a validation ledger: source, configuration, flight state, metric/band/directivity, residual, measurement uncertainty and applicability tags. Report an uncertainty budget by component; do not represent tree dispersion or learned/physics disagreement as a physics prediction interval. |

## What the literature says in more detail

1. **Do not use a single fitted offset to substitute for engine state.**
   NASA's broad jet assessment describes Stone/ST2JET as a fast, documented,
   state-of-the-art semi-empirical model with virtual sources for spectral
   directivity, but it is an assessment across a broad flow range, not proof
   for any new engine.  The Learjet comparison found the Stone estimate below
   flight EPNL by 1--2 EPNdB and specifically identifies exhaust temperature,
   aircraft position and microphone averaging as consequential comparison
   inputs.  For PNMF, this argues for an engine-deck contract plus test data,
   not a broad recalibration of a model frozen on A320-211.

2. **Airframe noise needs geometry that corresponds to the mechanism.**
   The 2022 NASA/Boeing 787-10 assessment is particularly actionable because
   it compares landing gear, slat, flap and trailing-edge components with
   flight data.  It reports interaction and modern-design mechanisms absent
   from older correlations.  PNMF should therefore retain individual sources,
   then add input fields and modules that map to those mechanisms.  A generic
   `airframe correction` would not be auditable or transferable.

3. **Installation is a real physics layer, not an optional cosmetic delta.**
   ANOPP2 was designed explicitly for component location, installation effects
   and propagation in non-uniform atmosphere/terrain at mixed fidelity.  The
   NASA D8 study separately modelled boundary-layer-ingestion effects on fan
   noise and shielding/reflection/diffraction using experiment.  Those facts
   support a modular installation layer, but they do *not* validate a generic
   shielding correction for every PNMF concept.

4. **Increase propagation complexity only where the scenario warrants it.**
   Straight-path free-field spreading plus molecular absorption remains a
   defensible screening baseline.  NASA's ray-tracing work says differences
   arise especially far from the source and at shallow elevation; it does not
   imply that every short-range reference NPD computation should use ray
   tracing.  This is why the upgrade should be optional and verification-led.

5. **Validation should follow a ladder.**
   Validate (a) source spectra/directivity, then (b) propagated component time
   histories, then (c) total SEL/LAmax, and finally (d) NPD-equivalent tables
   for a specified trajectory.  Record measurement uncertainty and hold out
   configuration/engine families where data permit.  NASA's assessment work
   supports this component-and-system approach; ECAC also requires auditable
   inputs, assumptions and intermediate results for reliable modelling.

## Recommended staged research plan

1. **Inputs and evidence first:** select one conventional aircraft/engine with
   a citable deck and component/flight measurements; freeze data version,
   units and intended operating points.
2. **Component validation:** test jet and fan spectra/directivity, then
   airframe components, against that evidence before combining them.
3. **Installation pilot:** implement one source-position plus shielding/
   scattering case with published validation bounds; leave other configurations
   unavailable.
4. **Segmented event pilot:** reproduce an ECAC reference trajectory/event
   while retaining today's reference trajectory as a regression baseline.
5. **Uncertainty and decision gate:** publish residuals and an uncertainty
   budget; only then decide whether the new modules are useful for additional
   designs.

## Sources (primary / first-party)

- [Guo and Thomas, *Assessment of Next Generation Airframe Noise Prediction Methods with PAA and ASN Flight Test Data* (NASA, 2022)](https://ntrs.nasa.gov/api/citations/20220006685/downloads/Assessment%20of%20Next%20Generation%20Airframe%20Noise%20Prediction%20Methods%20with%20PAA%20%26%20ASN%20Flight%20Test%20Data%20%2820220506%29.pdf?attachment=true) -- component-level 787-10 flight comparison and missing mechanisms.
- [Dahl, *A Process for Assessing NASA's Capability in Aircraft Noise Prediction Technology* (NASA/TM-2008-215268)](https://ntrs.nasa.gov/citations/20080032565) -- component/system comparison and uncertainty-assessment process.
- [Henderson, Huff and Berton, *Jet Noise Prediction Comparisons with Scale Model Tests and Learjet Flyover Data* (NASA, 2020)](https://ntrs.nasa.gov/citations/20200001113) -- evidence on Stone-model flight comparison and exhaust-temperature sensitivity.
- [Lopes and Burley, *Design of the Next Generation Aircraft Noise Prediction Program: ANOPP2* (NASA, 2011)](https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20110012482.pdf) -- mixed-fidelity architecture, installation and propagation scope.
- [Clark, Thomas and Guo, *Aircraft System Noise of the NASA D8 Subsonic Transport Concept* (NASA, 2021)](https://ntrs.nasa.gov/citations/20205003031) -- experimental treatment of BLI and shielding/reflection/diffraction in a system study.
- [Thomas, Czech and Doty, *High Bypass Ratio Jet Noise Reduction and Installation Effects Including Shielding Effectiveness* (NASA, 2013)](https://ntrs.nasa.gov/citations/20130003185) -- installation sensitivity and high-frequency shielding experiment.
- [Guo and Thomas, *Airframe Scattering of Engine Fan Noise* (NASA, 2025 preprint)](https://ntrs.nasa.gov/citations/20250007135) -- fan-source coherence and scattering method compared with Boeing 787 observations; promising but still a preprint.
- [ECAC Doc 29, 4th edition, Volume 1 (2016)](https://ecac-ceac.org/images/documents/ECAC-Doc_29_4th_edition_Dec_2016_Volume_1.pdf) -- operational-profile, segmentation, auditability and model-practice baseline.
- [Nark et al., *A Framework for Simulation of Aircraft Flyover Noise Through a Non-Standard Atmosphere* (NASA, 2012)](https://ntrs.nasa.gov/citations/20120010289) -- ray-path propagation applicability.

## Boundary

None of these sources makes PNMF's current or proposed physical route
certification-grade.  Each new component must remain provenance-labelled,
independently validated, and visibly unavailable outside its calibration and
evidence range.
