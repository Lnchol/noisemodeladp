# Component-physics presets

The Streamlit **Aircraft Designer** provides three easy-start presets whose
aircraft identifiers exist in PNMF's local EASA ANP v6.3 supplement. One
selection populates both ET/RF and component-physics inputs so their noise
results can be compared for the same aircraft. They remain starting points for
conceptual screening, not certified aircraft or engine decks.

| v6.3 aircraft | Engine | Published values used | Explicit estimates |
|---|---|---|---|
| `A320-270N` | PW1120G-JM | BPR 12:1; 81 in fan; 35.80 m span; 2 nose and 4 main wheels; published tire sizes | 24 fan blades; wing/high-lift and strut geometry |
| `A350-1041` | Trent XWB-97 | BPR 9.6:1; 118 in/22-blade fan; 64.75 m span; 2 nose and 12 main wheels | wheel diameters; wing/high-lift and strut geometry |
| `7773ER` | GE90-115B | BPR 9:1; 128 in/22-blade fan; 64.80 m span; 2 nose and 12 main wheels | wheel diameters; wing/high-lift and strut geometry |

Engine count, MTOW, MLW, noise chapter and maximum sea-level static thrust are
copied from each local v6.3 aircraft row. The public manufacturer sources
support only the fields named above. The current wing-area placeholder is

\[
S_\mathrm{wing,est} = \frac{b^2}{AR_\mathrm{assumed}},
\qquad AR_\mathrm{assumed}=9,
\]

where \(b\) is the published span. Flap area starts at \(0.17S\), slat area at
\(0.08S\), and unreferenced wheel/strut sizes remain editable estimates. These
assumptions appear as `estimated` in the result evidence table.

## First-party sources

### A320-270N

- [Airbus A320neo product specifications](https://www.aircraft.airbus.com/en/aircraft/a320-family/a320neo)
- [Pratt & Whitney GTF engine fast facts](https://prd-sc102-cdn.rtx.com/-/media/pw/newsroom/collateral/documents/commercial-engines/gtf-fast-facts.pdf)
- [Airbus A320 Aircraft Characteristics](https://aircraft.airbus.com/sites/g/files/jlcbta126/files/2024-06/AC_A320_0624.pdf)

### A350-1041

- [Airbus A350-1000 product specifications](https://www.aircraft.airbus.com/en/aircraft/a350/a350-1000)
- [Rolls-Royce Trent XWB technical data](https://www.rolls-royce.com/~/media/Files/R/Rolls-Royce/documents/civil-aerospace-downloads/High-Res-posters/High-Res-poster_Trent-XWB.pdf)
- [Airbus A350-1000 certification overview](https://www.airbus.com/en/newsroom/news/2017-11-the-a350-1000-is-certified-for-airline-service)
- [Airbus A350 Aircraft Characteristics](https://aircraft.airbus.com/sites/g/files/jlcbta126/files/2024-12/AC_A350_1224.pdf)

### 777-300ER

- [Boeing 777 design and characteristics](https://www.boeing.com/Commercial/777/design-highlights)
- [Boeing 777-300ER Airport Planning Characteristics](https://www.boeing.com/content/dam/boeing/v2/airports/acaps/777-200LR-300ER-F_Rev_G.pdf)
- [GE Aerospace GE90 history](https://www.geaerospace.com/company/about-us/history)
- [GE Aerospace composite fan blade history](https://www.geaerospace.com/news/ko/press-releases/commercial-engines/ges-composite-fan-blade-revolution-turns-20-years-old)

The detailed engine-deck form remains optional. A preset does not invent mass
flow, nozzle state, RPM, rotor-stator spacing, combustor state, or turbine
attenuation. Until complete data are supplied, the physics model retains its
documented simplified mixed-jet and estimated fan paths and omits core noise.
