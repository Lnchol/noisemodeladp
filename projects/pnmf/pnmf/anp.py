"""ANP database loader and joiner.

Reads the canonical combined EASA ANP datastore and exposes clean, joined
tables. The central
join is Aircraft <-> NPD_data on NPD_ID, which gives every NPD curve a
parametric descriptor row.

Storage: `build_datastore()` merges raw legacy-v2.3 and v6.3 CSV sources into
`anp_data.sqlite` with provenance. The legacy loose-file fallback remains only
for explicit compatibility and cannot satisfy the default v6.3 requirement.
This module also contains the QA gate and PredictionStore.
"""
from __future__ import annotations
import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Literal, overload
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_COLS = ['L_200ft', 'L_400ft', 'L_630ft', 'L_1000ft', 'L_2000ft',
             'L_4000ft', 'L_6300ft', 'L_10000ft', 'L_16000ft', 'L_25000ft']

class DataSourceError(RuntimeError):
    """A configured ANP source is absent or contributes no usable rows."""


class DataIntegrityError(RuntimeError):
    """ANP source tables cannot be merged without breaking their contracts."""


def project_path(root: str | os.PathLike | None = None) -> Path:
    """Resolve PNMF data relative to the application, never the caller CWD."""
    if root is None or str(root) in ("", "."):
        return PROJECT_ROOT
    path = Path(root).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


class ANPDatabase:
    """Loads and joins the ANP CSV database from a directory."""

    def __init__(self, root: str | os.PathLike | None = None,
                 *, require_v63: bool = True):
        self.root = str(project_path(root))
        # single-file datastore takes precedence over loose CSVs
        if str(self.root).endswith(".sqlite"):
            db_path = str(self.root)
        else:
            db_path = os.path.join(self.root, "anp_data.sqlite")
        self._sqlite = sqlite3.connect(db_path) if os.path.exists(db_path) else None
        try:
            self._validate_runtime_contract()
            self.aircraft = self._table("ANP2_3_Aircraft.csv")
            self.npd = self._table("ANP2_3_NPD_data.csv")
            self.jet_coeffs = self._table("ANP2_3_Jet_engine_coefficients.csv")
            self.prop_coeffs = self._table("ANP2_3_Propeller_engine_coefficients.csv",
                                           required=False)
            # optional tables (loaded lazily-tolerant)
            self.aero = self._table("ANP2_3_Aerodynamic_coefficients.csv", required=False)
            self.dep_steps = self._table("ANP2_3_Default_departure_procedural_steps.csv", required=False)
            self.app_steps = self._table("ANP2_3_Default_approach_procedural_steps.csv", required=False)
            self.profiles = self._table("ANP2_3_Default_fixed_point_profiles.csv", required=False)
            self.weights = self._table("ANP2_3_Default_weights.csv", required=False)
        finally:
            if self._sqlite is not None:
                self._sqlite.close()
                self._sqlite = None
        self._clean()
        if set(self.aircraft["Engine Type"].dropna().astype(str)) != {"Jet"}:
            raise DataIntegrityError(
                "datastore is not Jet-only; rebuild with pnmf_cli.py datastore"
            )
        if require_v63:
            self._require_v63_training_data()

    def _validate_runtime_contract(self) -> None:
        if self._sqlite is None:
            raise DataIntegrityError(
                "canonical Jet-only datastore is missing; run pnmf_cli.py datastore"
            )
        exists = self._sqlite.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='anp_meta'"
        ).fetchone()
        if not exists:
            raise DataIntegrityError(
                "datastore has no runtime population manifest; rebuild with "
                "pnmf_cli.py datastore"
            )
        row = self._sqlite.execute("SELECT * FROM anp_meta LIMIT 1").fetchone()
        columns = [item[1] for item in self._sqlite.execute(
            "PRAGMA table_info(anp_meta)"
        ).fetchall()]
        metadata = dict(zip(columns, row)) if row is not None else {}
        if metadata.get("population_scope") != POPULATION_SCOPE:
            raise DataIntegrityError(
                "datastore is not Jet-only; rebuild with pnmf_cli.py datastore"
            )
        if int(metadata.get("schema_version", -1)) != DATASTORE_SCHEMA_VERSION:
            raise DataIntegrityError(
                "stale datastore schema; rebuild with pnmf_cli.py datastore"
            )

    # overloads: required tables can never come back None (a missing one
    # raises), so only the required=False path is Optional
    @overload
    def _table(self, csv_name: str, required: Literal[True] = ...) -> pd.DataFrame: ...
    @overload
    def _table(self, csv_name: str, required: Literal[False]) -> pd.DataFrame | None: ...
    @overload
    def _table(self, csv_name: str, required: bool) -> pd.DataFrame | None: ...

    def _table(self, csv_name, required=True):
        if self._sqlite is not None:
            table = table_for_csv(csv_name)   # defined below (merged datastore)
            exists = self._sqlite.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone()
            if exists:
                return pd.read_sql_query(f'SELECT * FROM "{table}"', self._sqlite)
            if required:
                raise FileNotFoundError(
                    f"table {table!r} missing from datastore (rebuild with: "
                    f"pnmf_cli.py datastore)")
            return None
        return self._csv(csv_name, required)

    @overload
    def _csv(self, name: str, required: Literal[True] = ...) -> pd.DataFrame: ...
    @overload
    def _csv(self, name: str, required: Literal[False]) -> pd.DataFrame | None: ...
    @overload
    def _csv(self, name: str, required: bool) -> pd.DataFrame | None: ...

    def _csv(self, name, required=True):
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            if required:
                raise FileNotFoundError(path)
            return None
        return pd.read_csv(path, sep=';')

    def _clean(self):
        # Data hygiene (fault: raw ANP CSVs carry trailing whitespace in string
        # cells, e.g. Flap_ID 'T_05  ', which silently breaks joins): strip all
        # string columns in every loaded table.
        for tbl in (self.aircraft, self.npd, self.jet_coeffs, self.prop_coeffs,
                    self.aero, self.dep_steps, self.app_steps, self.profiles,
                    self.weights):
            if tbl is None:
                continue
            tbl.columns = [str(c).strip() for c in tbl.columns]
            for c in tbl.columns:
                if tbl[c].dtype == object or str(tbl[c].dtype).startswith('str'):
                    tbl[c] = tbl[c].astype('string').str.strip()
        a = self.aircraft
        # numeric coercions
        for c in ['Number Of Engines', 'Max Gross Takeoff Weight (lb)',
                  'Max Gross Landing Weight (lb)', 'Max Landing Distance (ft)',
                  'Max Sea Level Static Thrust (lb)', 'Noise Chapter']:
            a[c] = pd.to_numeric(a[c], errors='coerce')
        n = self.npd
        for c in ['Power Setting'] + DIST_COLS:
            n[c] = pd.to_numeric(n[c], errors='coerce')

    def _require_v63_training_data(self):
        for name, table in (("aircraft", self.aircraft), ("NPD", self.npd)):
            if "source_dataset" not in table:
                raise DataSourceError(
                    f"{name} table has no source provenance; ANP v6.3 is "
                    "required. Rebuild with: pnmf_cli.py datastore")
        v63_npd = self.npd[
            self.npd["source_dataset"] == "supplement_v6.3"]
        v63_aircraft = self.aircraft[
            self.aircraft["source_dataset"] == "supplement_v6.3"]
        if v63_npd.empty or v63_aircraft.empty:
            raise DataSourceError(
                "ANP v6.3 is required but contributes zero usable training "
                "rows; verify 03_data/EASA_ANP_database_v6.3 and rebuild")

    # ---- parametric descriptor per NPD_ID -------------------------------
    def param_table(self) -> pd.DataFrame:
        """One parametric descriptor row per NPD_ID (the model's X features)."""
        cached = getattr(self, "_cached_param_table", None)
        if cached is not None:
            return cached
        a = self.aircraft.dropna(subset=['NPD_ID']).copy()
        # if several aircraft share an NPD_ID, keep the heaviest (representative)
        a = (a.sort_values('Max Gross Takeoff Weight (lb)', ascending=False)
               .drop_duplicates('NPD_ID', keep='first')
               .set_index('NPD_ID'))
        self._cached_param_table = a
        return a

    def curve(self, npd_id: str, metric: str, op_mode: str) -> pd.DataFrame:
        """Return the NPD rows (power settings x 10 distances) for one curve set."""
        n = self.npd
        sel = n[(n['NPD_ID'] == npd_id) &
                (n['Noise Metric'] == metric) &
                (n['Op Mode'] == op_mode)].sort_values('Power Setting')
        return sel

    def list_curve_sets(self, metric: str, op_mode: str):
        """All NPD_IDs that have a curve set for the given metric/mode."""
        n = self.npd
        ids = n[(n['Noise Metric'] == metric) &
                (n['Op Mode'] == op_mode)]['NPD_ID'].unique()
        params = self.param_table()
        return [i for i in ids if i in params.index]

    def summary(self) -> dict:
        result = {
            "n_aircraft": len(self.aircraft),
            "n_npd_sets": self.npd['NPD_ID'].nunique(),
            "n_npd_rows": len(self.npd),
            "metrics": sorted(self.npd['Noise Metric'].unique().tolist()),
            "op_modes": sorted(self.npd['Op Mode'].unique().tolist()),
            "engine_types": self.aircraft['Engine Type'].value_counts().to_dict(),
            "population_scope": POPULATION_SCOPE,
        }
        if "source_dataset" in self.npd:
            result["npd_rows_by_source"] = (
                self.npd["source_dataset"].value_counts().sort_index().to_dict())
        return result

    def dataset_manifest(self) -> pd.DataFrame:
        """Inspectable provenance summary embedded in the canonical sqlite."""
        db_path = (self.root if self.root.endswith(".sqlite")
                   else os.path.join(self.root, DB_FILENAME))
        if not os.path.exists(db_path):
            raise DataSourceError("dataset manifest requires anp_data.sqlite")
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='anp_dataset_manifest'").fetchone()
            if not exists:
                raise DataIntegrityError(
                    "datastore has no dataset manifest; rebuild with "
                    "pnmf_cli.py datastore")
            return pd.read_sql_query(
                "SELECT * FROM anp_dataset_manifest "
                "ORDER BY logical_table, source_dataset", conn)

    # ---- nearest-neighbor lookup (substitution-style) --------------------
    def nearest_aircraft(self, mtow_lb, engine_type=None, n_engines=None, n=3,
                         restrict_to=None):
        """Find the n closest ANP aircraft by log(MTOW) [+ engine-type match],
        mirroring the criteria EASA's own substitution methodology uses
        (MTOW, thrust/MTOW ratio, engine count) to assign a proxy aircraft to
        one that isn't explicitly in the database. Used here to borrow a
        representative default procedure (departure/approach profile) for a
        parametric/future aircraft that has no performance model of its own.

        restrict_to: optional iterable of ACFT_IDs to search within (e.g. only
        aircraft that actually have a usable fixed-point profile - the ANP
        fixed-point-profile table only covers a small demonstration subset).

        Returns a DataFrame of candidate ACFT_ID rows sorted by distance.
        """
        a = self.aircraft.dropna(subset=['Max Gross Takeoff Weight (lb)']).copy()
        if restrict_to is not None:
            a = a[a['ACFT_ID'].isin(set(restrict_to))]
        if engine_type is not None:
            same = a[a['Engine Type'] == engine_type]
            if len(same) >= n:
                a = same
        target = np.log10(mtow_lb)
        a['_dist'] = (np.log10(a['Max Gross Takeoff Weight (lb)']) - target).abs()
        if n_engines is not None and 'Number Of Engines' in a:
            a['_dist'] += 0.15 * (a['Number Of Engines'] - n_engines).abs()
        return a.sort_values('_dist').head(n).drop(columns='_dist')

    def nearest_npd_ids(self, mtow_lb, engine_type=None, n_engines=None, n=3):
        """n nearest real aircraft that HAVE NPD curves: [(acft_id, npd_id), ...],
        deduped on NPD_ID (several ACFT_IDs share one), ordered by distance."""
        cand = self.nearest_aircraft(mtow_lb, engine_type, n_engines,
                                     n=max(4 * n, 12))
        params = self.param_table()
        out, seen = [], set()
        for row in cand[['ACFT_ID', 'NPD_ID']].itertuples(index=False):
            npd_id = row.NPD_ID
            if pd.isna(npd_id) or npd_id not in params.index or npd_id in seen:
                continue
            seen.add(npd_id)
            out.append((str(row.ACFT_ID), str(npd_id)))
            if len(out) >= n:
                break
        return out

    def aircraft_with_profile(self, op_type):
        """ACFT_IDs that have a usable fixed-point profile for op_type ('D'/'A').
        The ANP fixed-point-profile table only covers a small demonstration
        subset of the full aircraft list, so callers needing a trajectory
        should restrict their aircraft search to this set first."""
        if self.profiles is None:
            return set()
        sub = self.profiles[self.profiles['Op Type'] == op_type]
        return set(sub['ACFT_ID'].unique())

    # ---- optional: EASA/ECAC substitution table (independent, large-n ----
    #      certified-noise ground truth used for external validation) -----
    def load_substitution_table(self, path):
        """Load the 'by aircraft configuration' sheet of the published ANP
        substitution workbook: ~19.5k real certificated aircraft records with
        measured LATERAL/FLYOVER/APPROACH EPNL, MTOW, engine count, and each
        record's own noise mismatch (DELTA_DEP_dB/DELTA_APP_dB) versus its
        assigned ANP proxy. This is independent of the 111 NPD-curve aircraft
        used to train/validate the surrogate, so it is useful as an external
        sanity check and as a real-world accuracy benchmark for substitution-
        based noise estimation in general.
        """
        df = pd.read_excel(path, sheet_name="by aircraft configuration")
        df = df.rename(columns={
            'MTOW_KG': 'mtow_kg', 'MLW_KG': 'mlw_kg',
            'ENGINE_NUMBER': 'n_engines', 'ENGINE_TYPE': 'engine',
            'LATERAL_LEVEL_EPNdB': 'lateral_epndb',
            'FLYOVER_LEVEL_EPNdB': 'flyover_epndb',
            'APPROACH_LEVEL_EPNdB': 'approach_epndb',
            'ANP_PROXY': 'anp_proxy', 'DELTA_DEP_dB': 'delta_dep_db',
            'DELTA_APP_dB': 'delta_app_db',
        })
        self.substitutions = df
        return df


# ===========================================================================
# section: datastore (merged)
# ===========================================================================

"""Single-file SQLite datastore: ANP truth tables + guarded ML predictions.

Replaces the nine loose ``ANP2_3_*.csv`` files with one ``anp_data.sqlite``
database and gives future-aircraft predictions a durable, clearly separated
home inside the same file.

Two hard rules keep real and generated data apart ("no false data"):

1. The ANP truth tables live under the ``anp_*`` prefix and are written by
   exactly one function - :func:`build_datastore`, which converts the CSVs
   verbatim. Nothing else in the framework writes to them.
2. Model output goes only into ``predicted_aircraft`` / ``predicted_npd``,
   and only after passing :func:`qa_check`: finite values, plausible dB
   bounds, monotone non-increasing with distance. Tables that fail are
   rejected outright; tables that pass but carry high cross-tree uncertainty
   (extrapolation) or a large physics-route disagreement are stored flagged
   ``caution`` so downstream consumers can filter on ``qa_status``.
"""
import contextlib
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile

import numpy as np
import pandas as pd


DB_FILENAME = "anp_data.sqlite"
DATASTORE_SCHEMA_VERSION = 2
POPULATION_SCOPE = "jet_only"
SOURCE_URLS = {
    "legacy_v2.3": (
        "https://www.easa.europa.eu/en/domains/environment/"
        "policy-support-and-research/aircraft-noise-and-performance-anp-data"
    ),
    "supplement_v6.3": (
        "https://www.easa.europa.eu/en/domains/environment/"
        "policy-support-and-research/aircraft-noise-and-performance-anp-data"
    ),
}

#: CSV file -> sqlite table. Same set (and required-ness) as ANPDatabase.
CSV_TABLES = {
    "ANP2_3_Aircraft.csv": "anp_aircraft",
    "ANP2_3_NPD_data.csv": "anp_npd_data",
    "ANP2_3_Jet_engine_coefficients.csv": "anp_jet_engine_coefficients",
    "ANP2_3_Propeller_engine_coefficients.csv": "anp_propeller_engine_coefficients",
    "ANP2_3_Aerodynamic_coefficients.csv": "anp_aerodynamic_coefficients",
    "ANP2_3_Default_departure_procedural_steps.csv": "anp_default_departure_procedural_steps",
    "ANP2_3_Default_approach_procedural_steps.csv": "anp_default_approach_procedural_steps",
    "ANP2_3_Default_fixed_point_profiles.csv": "anp_default_fixed_point_profiles",
    "ANP2_3_Default_weights.csv": "anp_default_weights",
}
REQUIRED_CSVS = ("ANP2_3_Aircraft.csv", "ANP2_3_NPD_data.csv",
                 "ANP2_3_Jet_engine_coefficients.csv")

RAW_SOURCES = {
    "legacy_v2.3": {
        "directory": "EASA_ANP_LEGACY_database_v2.3",
        "delimiter": ";",
        "files": {
            "ANP2_3_Aircraft.csv": "ANP2.3_Aircraft.csv",
            "ANP2_3_NPD_data.csv": "ANP2.3_NPD_data.csv",
            "ANP2_3_Jet_engine_coefficients.csv":
                "ANP2.3_Jet_engine_coefficients.csv",
            "ANP2_3_Propeller_engine_coefficients.csv":
                "ANP2.3_Propeller_engine_coefficients.csv",
            "ANP2_3_Aerodynamic_coefficients.csv":
                "ANP2.3_Aerodynamic_coefficients.csv",
            "ANP2_3_Default_departure_procedural_steps.csv":
                "ANP2.3_Default_departure_procedural_steps.csv",
            "ANP2_3_Default_approach_procedural_steps.csv":
                "ANP2.3_Default_approach_procedural_steps.csv",
            "ANP2_3_Default_fixed_point_profiles.csv":
                "ANP2.3_Default_fixed_point_profiles.csv",
            "ANP2_3_Default_weights.csv": "ANP2.3_Default_weights.csv",
        },
    },
    "supplement_v6.3": {
        "directory": "EASA_ANP_database_v6.3",
        "delimiter": ",",
        "files": {
            "ANP2_3_Aircraft.csv": "EASA_ANP_database_Aircraft_v6.3.csv",
            "ANP2_3_NPD_data.csv": "EASA_ANP_database_NPD_Data_v6.3.csv",
            "ANP2_3_Jet_engine_coefficients.csv":
                "EASA_ANP_database_Jet_Engine_Coefficients_v6.3.csv",
            "ANP2_3_Aerodynamic_coefficients.csv":
                "EASA_ANP_database_Aerodynamic_Coefficients_v6.3.csv",
            "ANP2_3_Default_departure_procedural_steps.csv":
                "EASA_ANP_database_Default_Departure_Procedural_Steps_v6.3.csv",
            "ANP2_3_Default_approach_procedural_steps.csv":
                "EASA_ANP_database_Default_Approach_Procedural_Steps_v6.3.csv",
            "ANP2_3_Default_fixed_point_profiles.csv":
                "EASA_ANP_database_Default_Fixed_Point_Profiles_v6.3.csv",
            "ANP2_3_Default_weights.csv":
                "EASA_ANP_database_Default_Weights_v6.3.csv",
        },
    },
}

MERGE_KEYS = {
    # ACFT_ID 7773ER exists in both releases but points at different NPD_IDs.
    # Preserve both source records so neither certified curve set is orphaned.
    "ANP2_3_Aircraft.csv": ["ACFT_ID", "NPD_ID"],
    "ANP2_3_NPD_data.csv":
        ["NPD_ID", "Noise Metric", "Op Mode", "Power Setting"],
    "ANP2_3_Jet_engine_coefficients.csv": ["ACFT_ID", "Thrust Rating"],
    "ANP2_3_Propeller_engine_coefficients.csv":
        ["ACFT_ID", "Thrust Rating"],
    "ANP2_3_Aerodynamic_coefficients.csv": ["ACFT_ID", "Op Type", "Flap_ID"],
    "ANP2_3_Default_departure_procedural_steps.csv":
        ["ACFT_ID", "Profile_ID", "Stage Length", "Step Number"],
    "ANP2_3_Default_approach_procedural_steps.csv":
        ["ACFT_ID", "Profile_ID", "Step Number"],
    "ANP2_3_Default_fixed_point_profiles.csv":
        ["ACFT_ID", "Op Type", "Profile_ID", "Stage Length", "Point Number"],
    "ANP2_3_Default_weights.csv": ["ACFT_ID", "Stage Length"],
}

STD_COLS = ["std_" + c for c in DIST_COLS]


def table_for_csv(csv_name: str) -> str:
    return CSV_TABLES[csv_name]


def _normalise_raw(df: pd.DataFrame, source: str, filename: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype).startswith("str"):
            df[col] = df[col].astype("string").str.strip()
    for col in ("Op Mode", "Op Type"):
        if col in df:
            df[col] = df[col].str.upper()
    df["source_dataset"] = source
    df["source_file"] = filename
    return df


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_ledger(root: Path, manifest: list[dict]) -> list[dict]:
    known = {(row["source_dataset"], row["source_file"]) for row in manifest}
    records = list(manifest)
    for source, config in RAW_SOURCES.items():
        source_dir = root / "03_data" / config["directory"]
        if not source_dir.is_dir():
            continue
        table_by_file = {
            filename: CSV_TABLES[logical_name]
            for logical_name, filename in config["files"].items()
        }
        for path in sorted(source_dir.iterdir()):
            if not path.is_file() or (source, path.name) in known:
                continue
            records.append({
                "logical_table": table_by_file.get(path.name, "source_file"),
                "source_dataset": source,
                "source_file": path.name,
                "source_rows": None,
                "combined_rows": None,
                "duplicates_removed_total": None,
                "merge_key": None,
                "duplicate_policy": "supplement_v6.3_wins",
                "source_release": source,
                "source_url": SOURCE_URLS[source],
                "source_sha256": _sha256_file(path),
            })
    return records


def _load_raw_sources(root: Path, expect_v63: bool) -> tuple[dict, list]:
    data_root = root / "03_data"
    loaded: dict[str, list[pd.DataFrame]] = {
        name: [] for name in CSV_TABLES}
    manifest = []
    for source, config in RAW_SOURCES.items():
        required = source == "legacy_v2.3" or expect_v63
        source_dir = data_root / config["directory"]
        if required and not source_dir.is_dir():
            raise DataSourceError(
                f"required ANP source directory missing: {source_dir}")
        if not source_dir.is_dir():
            continue
        for logical_name, filename in config["files"].items():
            path = source_dir / filename
            table_required = logical_name in REQUIRED_CSVS
            if not path.is_file():
                if required and table_required:
                    raise DataSourceError(
                        f"{source} required table missing: {path}")
                continue
            df = pd.read_csv(path, sep=config["delimiter"])
            if len(df.columns) == 1:
                raise DataSourceError(
                    f"{source} delimiter/schema mismatch in {path}")
            df = _normalise_raw(df, source, filename)
            loaded[logical_name].append(df)
            manifest.append({
                "logical_table": CSV_TABLES[logical_name],
                "source_dataset": source,
                "source_file": filename,
                "source_rows": len(df),
                "source_release": source,
                "source_url": SOURCE_URLS[source],
                "source_sha256": _sha256_file(path),
            })
    if expect_v63:
        v63_npd = [
            f for f in loaded["ANP2_3_NPD_data.csv"]
            if not f.empty and f["source_dataset"].iat[0] == "supplement_v6.3"]
        if not v63_npd or sum(len(f) for f in v63_npd) == 0:
            raise DataSourceError(
                "ANP v6.3 was configured as required but contributed zero "
                "usable NPD training rows")
    return loaded, manifest


def _merge_sources(loaded: dict, manifest: list) -> dict[str, pd.DataFrame]:
    merged = {}
    for logical_name, frames in loaded.items():
        if not frames:
            continue
        expected = [c for c in frames[0].columns
                    if c not in ("source_dataset", "source_file")]
        for frame in frames[1:]:
            actual = [c for c in frame.columns
                      if c not in ("source_dataset", "source_file")]
            if actual != expected:
                raise DataIntegrityError(
                    f"schema mismatch for {logical_name}: "
                    f"{expected} != {actual}")
        combined = pd.concat(frames, ignore_index=True)
        keys = MERGE_KEYS[logical_name]
        missing_keys = [c for c in keys if c not in combined]
        if missing_keys:
            raise DataIntegrityError(
                f"{logical_name} missing merge keys {missing_keys}")
        before = len(combined)
        # Source order is legacy then supplement; keep='last' makes the newer
        # supplement win deterministic business-key collisions.
        combined = combined.drop_duplicates(keys, keep="last").reset_index(drop=True)
        merged[logical_name] = combined
        table = CSV_TABLES[logical_name]
        for row in manifest:
            if row["logical_table"] == table:
                row["merge_key"] = json.dumps(keys)
                row["duplicate_policy"] = "supplement_v6.3_wins"
                row["combined_rows"] = len(combined)
                row["duplicates_removed_total"] = before - len(combined)
    return merged


def _jet_only_tables(
    merged: dict[str, pd.DataFrame], manifest: list[dict]
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    aircraft_name = "ANP2_3_Aircraft.csv"
    npd_name = "ANP2_3_NPD_data.csv"
    aircraft = merged[aircraft_name]
    npd = merged[npd_name]
    jet_aircraft = aircraft.loc[
        aircraft["Engine Type"].astype("string").eq("Jet")
    ].copy()
    jet_acft_ids = set(jet_aircraft["ACFT_ID"].dropna().astype(str))
    candidate_ids = set(jet_aircraft["NPD_ID"].dropna().astype(str))
    task_pairs = {
        (metric, mode)
        for metric in ("SEL", "LAmax", "EPNL", "PNLTM")
        for mode in ("A", "D")
    }
    npd = npd.loc[npd["NPD_ID"].astype(str).isin(candidate_ids)].copy()
    complete_ids = {
        str(npd_id)
        for npd_id, group in npd.groupby("NPD_ID", sort=True)
        if set(zip(group["Noise Metric"], group["Op Mode"])) == task_pairs
    }
    descriptors = jet_aircraft.loc[
        jet_aircraft["NPD_ID"].astype(str).isin(complete_ids)
    ]
    unsupported = descriptors.loc[
        descriptors["Power Parameter"].astype(str) != "CNT (lb)"
    ]
    if not unsupported.empty:
        raise DataIntegrityError(
            "Jet runtime contains unsupported power parameters: "
            + ", ".join(sorted(unsupported["Power Parameter"].astype(str).unique()))
        )
    selected_ids = set(descriptors["NPD_ID"].dropna().astype(str))
    result: dict[str, pd.DataFrame] = {}
    for logical_name, frame in merged.items():
        if logical_name == "ANP2_3_Propeller_engine_coefficients.csv":
            continue
        filtered = frame.copy()
        if logical_name == aircraft_name:
            filtered = jet_aircraft.loc[
                jet_aircraft["NPD_ID"].astype(str).isin(selected_ids)
            ].copy()
        elif logical_name == npd_name:
            filtered = npd.loc[
                npd["NPD_ID"].astype(str).isin(selected_ids)
            ].copy()
        elif "ACFT_ID" in filtered.columns:
            filtered = filtered.loc[
                filtered["ACFT_ID"].astype(str).isin(jet_acft_ids)
            ].copy()
        result[logical_name] = filtered.reset_index(drop=True)
    exclusions = []
    for logical_name, frame in merged.items():
        if logical_name not in result:
            exclusions.append({
                "logical_table": CSV_TABLES[logical_name],
                "reason": "non-Jet runtime table excluded",
                "source_rows": len(frame),
                "excluded_rows": len(frame),
            })
            continue
        before = len(frame)
        after = len(result[logical_name])
        if before != after:
            exclusions.append({
                "logical_table": CSV_TABLES[logical_name],
                "reason": "non-Jet or incomplete Jet rows excluded",
                "source_rows": before,
                "excluded_rows": before - after,
            })
    manifest.extend(exclusions)
    return result, manifest


def _validate_truth(merged: dict, expect_v63: bool) -> None:
    for required in REQUIRED_CSVS:
        if required not in merged or merged[required].empty:
            raise DataIntegrityError(f"required merged table empty: {required}")
    aircraft = merged["ANP2_3_Aircraft.csv"]
    npd = merged["ANP2_3_NPD_data.csv"]
    aircraft_ids = set(aircraft["NPD_ID"].dropna())
    npd_ids = set(npd["NPD_ID"].dropna())
    if aircraft_ids != npd_ids:
        raise DataIntegrityError(
            "Aircraft/NPD referential integrity failed: "
            f"aircraft-only={sorted(aircraft_ids - npd_ids)}, "
            f"NPD-only={sorted(npd_ids - aircraft_ids)}")
    if expect_v63:
        v63 = npd[npd["source_dataset"] == "supplement_v6.3"]
        if v63.empty:
            raise DataSourceError(
                "ANP v6.3 contributed zero usable training rows after merge")
        v63_aircraft = set(
            aircraft.loc[aircraft["source_dataset"] == "supplement_v6.3",
                         "NPD_ID"].dropna())
        if not set(v63["NPD_ID"]).issubset(v63_aircraft):
            raise DataIntegrityError(
                "v6.3 NPD rows lost their v6.3 aircraft descriptors")


def _read_jet_predictions(db_target: Path) -> dict[str, pd.DataFrame]:
    if not db_target.exists():
        return {"aircraft": pd.DataFrame(), "npd": pd.DataFrame()}
    try:
        with contextlib.closing(sqlite3.connect(db_target)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"predicted_aircraft", "predicted_npd"}.issubset(tables):
                return {"aircraft": pd.DataFrame(), "npd": pd.DataFrame()}
            aircraft = pd.read_sql_query("SELECT * FROM predicted_aircraft", conn)
            npd = pd.read_sql_query("SELECT * FROM predicted_npd", conn)
    except sqlite3.DatabaseError:
        return {"aircraft": pd.DataFrame(), "npd": pd.DataFrame()}
    if "engine_type" not in aircraft.columns:
        return {"aircraft": pd.DataFrame(), "npd": pd.DataFrame()}
    retained = aircraft.loc[
        aircraft["engine_type"].astype("string").eq("Jet")
    ].copy()
    keys = retained[["name", "model"]]
    if keys.empty:
        npd = npd.iloc[0:0].copy()
    else:
        npd = npd.merge(keys, on=["name", "model"], how="inner")
    return {"aircraft": retained, "npd": npd}


def _write_predictions(conn: sqlite3.Connection,
                       predictions: dict[str, pd.DataFrame]) -> None:
    conn.execute(_AIRCRAFT_DDL)
    conn.execute(_NPD_DDL)
    for table, frame in predictions.items():
        if not frame.empty:
            frame.to_sql(
                "predicted_aircraft" if table == "aircraft" else "predicted_npd",
                conn,
                if_exists="append",
                index=False,
            )


def _prediction_rebuild_manifest(
    db_target: Path, predictions: dict[str, pd.DataFrame]
) -> list[dict[str, str | int]]:
    before = {"aircraft": 0, "npd": 0}
    if db_target.exists():
        try:
            with contextlib.closing(sqlite3.connect(db_target)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for key, table in (("aircraft", "predicted_aircraft"), ("npd", "predicted_npd")):
                    if table in tables:
                        before[key] = int(
                            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        )
        except sqlite3.DatabaseError:
            before = {"aircraft": 0, "npd": 0}
    rows = []
    for key, table in (("aircraft", "predicted_aircraft"), ("npd", "predicted_npd")):
        retained = int(len(predictions[key]))
        rows.append({
            "entity": table,
            "before_rows": before[key],
            "retained_jet_rows": retained,
            "discarded_non_jet_rows": before[key] - retained,
            "discard_reason": "engine_type != Jet",
        })
    return rows


def build_datastore(root: str | os.PathLike | None = None,
                    db_path: str | os.PathLike | None = None,
                    *, expect_v63: bool = True) -> str:
    """Build canonical truth tables from raw v2.3 plus v6.3 CSV sources.

    The legacy fleet remains the base corpus. Business-key collisions are
    resolved deterministically in favour of the newer v6.3 supplement. Truth
    tables are replaced transactionally; predicted/model-trial tables are
    never addressed by this function.
    """
    root_path = project_path(root)
    if db_path is None:
        db_target = root_path / DB_FILENAME
    else:
        candidate = Path(db_path).expanduser()
        db_target = (candidate if candidate.is_absolute()
                     else root_path / candidate).resolve()
    loaded, manifest = _load_raw_sources(root_path, expect_v63)
    merged = _merge_sources(loaded, manifest)
    manifest = _source_ledger(root_path, manifest)
    merged, manifest = _jet_only_tables(merged, manifest)
    _validate_truth(merged, expect_v63)
    counts = {}
    db_target.parent.mkdir(parents=True, exist_ok=True)
    predictions = _read_jet_predictions(db_target)
    prediction_manifest = _prediction_rebuild_manifest(db_target, predictions)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{db_target.stem}.", suffix=".sqlite.tmp",
        dir=db_target.parent,
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    try:
        with contextlib.closing(sqlite3.connect(temporary_path)) as conn, conn:
            for logical_name, df in merged.items():
                table = CSV_TABLES[logical_name]
                df.to_sql(table, conn, if_exists="replace", index=False)
                counts[table] = len(df)
            pd.DataFrame(manifest).to_sql(
                "anp_dataset_manifest", conn, if_exists="replace", index=False)
            exclusion_rows = [
                row for row in manifest if "excluded_rows" in row
            ]
            pd.DataFrame(exclusion_rows).to_sql(
                "anp_exclusion_manifest", conn, if_exists="replace", index=False
            )
            pd.DataFrame(prediction_manifest).to_sql(
                "anp_prediction_rebuild_manifest", conn,
                if_exists="replace", index=False,
            )
            source_hashes = {
                f"{row.get('source_dataset')}:{row.get('source_file')}": row.get(
                    "source_sha256"
                )
                for row in manifest
                if row.get("source_sha256")
            }
            meta = pd.DataFrame([{
                "created_utc": _utcnow(),
                "source": "EASA ANP legacy v2.3 + v6.3 CSV supplement",
                "tables": json.dumps(counts, sort_keys=True),
                "expect_v63": int(expect_v63),
                "duplicate_policy": "supplement_v6.3_wins",
                "schema_version": DATASTORE_SCHEMA_VERSION,
                "population_scope": POPULATION_SCOPE,
                "engine_type": "Jet",
                "source_hashes": json.dumps(source_hashes, sort_keys=True),
            }])
            meta.to_sql("anp_meta", conn, if_exists="replace", index=False)
            _write_predictions(conn, predictions)
        try:
            os.replace(temporary_path, db_target)
        except PermissionError:
            shutil.copyfile(temporary_path, db_target)
            temporary_path.unlink()
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return str(db_target)


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# QA gate for predictions
# ---------------------------------------------------------------------------

def qa_check(P, L, std=None, *, bounds=(20.0, 160.0), std_caution_db=3.0,
             crosscheck_db=None, crosscheck_caution_db=5.0):
    """Validate one predicted NPD table before it may enter the database.

    Returns (status, reasons): status is 'ok', 'caution' or 'rejected'.
    Hard rejections (never stored): non-finite values, levels outside
    ``bounds`` dB, level increasing with distance, duplicate power settings.
    Caution flags (stored, but marked): mean cross-tree std above
    ``std_caution_db`` (the model is extrapolating), or mean |disagreement|
    with the independent physics route above ``crosscheck_caution_db``.
    """
    P = np.atleast_1d(np.asarray(P, float))
    L = np.atleast_2d(np.asarray(L, float))
    reasons = []
    if not np.isfinite(L).all():
        reasons.append("non-finite levels")
    else:
        if L.min() < bounds[0] or L.max() > bounds[1]:
            reasons.append(f"levels outside plausible range "
                           f"[{bounds[0]:.0f}, {bounds[1]:.0f}] dB "
                           f"(got {L.min():.1f}..{L.max():.1f})")
        if (np.diff(L, axis=1) > 1e-6).any():
            reasons.append("level increases with distance (unphysical)")
    if not np.isfinite(P).all() or np.unique(P).size != P.size:
        reasons.append("invalid or duplicate power settings")
    if reasons:
        return "rejected", reasons

    flags = []
    if std is not None:
        std = np.asarray(std, float)
        if np.isfinite(std).any():
            mean_std = float(np.nanmean(std))
            if mean_std > std_caution_db:
                flags.append(f"high model uncertainty (mean cross-tree std "
                             f"{mean_std:.2f} dB > {std_caution_db} dB) - "
                             f"likely extrapolation")
    if crosscheck_db is not None and np.isfinite(crosscheck_db):
        if crosscheck_db > crosscheck_caution_db:
            flags.append(f"independent physics route disagrees by "
                         f"{crosscheck_db:.1f} dB mean "
                         f"(> {crosscheck_caution_db} dB)")
    return ("caution", flags) if flags else ("ok", [])


# ---------------------------------------------------------------------------
# Prediction store
# ---------------------------------------------------------------------------

_AIRCRAFT_DDL = """CREATE TABLE IF NOT EXISTS predicted_aircraft (
    name TEXT NOT NULL, model TEXT NOT NULL,
    engine_type TEXT, n_engines INTEGER,
    max_static_thrust_lb REAL, mtow_lb REAL, mlw_lb REAL,
    bypass_ratio REAL, noise_chapter INTEGER,
    qa_status TEXT, physics_crosscheck TEXT, created_utc TEXT,
    feature_schema TEXT, training_population TEXT,
    validation_report_sha256 TEXT,
    PRIMARY KEY (name, model)
)"""

_NPD_DDL = ("CREATE TABLE IF NOT EXISTS predicted_npd (\n"
            "    name TEXT NOT NULL, model TEXT NOT NULL,\n"
            "    metric TEXT NOT NULL, op_mode TEXT NOT NULL,\n"
            "    power_parameter TEXT, power_setting REAL NOT NULL,\n"
            + ",\n".join(f"    {c} REAL" for c in DIST_COLS) + ",\n"
            + ",\n".join(f"    {c} REAL" for c in STD_COLS) + ",\n"
            "    qa_status TEXT, qa_notes TEXT, created_utc TEXT\n"
            ")")


class PredictionStore:
    """Reads/writes the ``predicted_*`` tables of the datastore. Never touches
    the ``anp_*`` truth tables (writes are limited to the two DDLs above)."""

    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise FileNotFoundError(
                f"{db_path} not found - run build_datastore first")
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(_AIRCRAFT_DDL)
        conn.execute(_NPD_DDL)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(predicted_aircraft)")
        }
        for name in ("feature_schema", "training_population",
                     "validation_report_sha256"):
            if name not in columns:
                conn.execute(f"ALTER TABLE predicted_aircraft ADD COLUMN {name} TEXT")
        return conn

    # ---- write -----------------------------------------------------------
    def add(self, aircraft, tables: dict, uncertainty: dict | None = None,
            model: str = "et-jet_merged-jet-v2", crosscheck: dict | None = None,
            replace: bool = True, metadata: dict | None = None):
        """Store the predicted NPD tables for one aircraft, gated by qa_check.

        aircraft    : ParametricAircraft
        tables      : {(metric, op_mode): NPDTable}     (NoisePrediction.tables)
        uncertainty : {(metric, op_mode): (P,10) std or None}
        crosscheck  : {metric: mean |delta| dB vs physics route}, optional
        Returns {(metric, op_mode): (status, reasons)}; rejected tables are
        NOT written. The aircraft row records the worst status of its tables.
        """
        if aircraft.engine_type != "Jet":
            raise ValueError("PredictionStore accepts Jet aircraft only")
        uncertainty = uncertainty or {}
        crosscheck = crosscheck or {}
        metadata = metadata or {}
        now = _utcnow()
        results, npd_rows = {}, []
        for (metric, om), tbl in tables.items():
            std = uncertainty.get((metric, om))
            status, reasons = qa_check(
                tbl.P, tbl.L, std, crosscheck_db=crosscheck.get(metric))
            results[(metric, om)] = (status, reasons)
            if status == "rejected":
                continue
            S = (np.asarray(std, float) if std is not None
                 else np.full_like(tbl.L, np.nan))
            for i, p in enumerate(tbl.P):
                row = {"name": aircraft.name, "model": model,
                       "metric": metric, "op_mode": om,
                       "power_parameter": tbl.power_param,
                       "power_setting": float(p),
                       "qa_status": status,
                       "qa_notes": "; ".join(reasons),
                       "created_utc": now}
                row.update({c: float(tbl.L[i, j])
                            for j, c in enumerate(DIST_COLS)})
                row.update({c: (float(S[i, j]) if np.isfinite(S[i, j])
                                else None)
                            for j, c in enumerate(STD_COLS)})
                npd_rows.append(row)

        statuses = [s for s, _ in results.values()]
        overall = ("rejected" if not npd_rows
                   else "caution" if "caution" in statuses else "ok")
        with contextlib.closing(self._conn()) as conn, conn:
            if replace:
                conn.execute("DELETE FROM predicted_npd WHERE name=? AND model=?",
                             (aircraft.name, model))
                conn.execute("DELETE FROM predicted_aircraft WHERE name=? AND model=?",
                             (aircraft.name, model))
            if npd_rows:
                pd.DataFrame(npd_rows).to_sql("predicted_npd", conn,
                                              if_exists="append", index=False)
                ac_row = {
                    "name": aircraft.name, "model": model,
                    "engine_type": aircraft.engine_type,
                    "n_engines": int(aircraft.n_engines),
                    "max_static_thrust_lb": float(aircraft.max_static_thrust_lb),
                    "mtow_lb": float(aircraft.mtow_lb),
                    "mlw_lb": float(aircraft.mlw_lb),
                    "bypass_ratio": (float(aircraft.bypass_ratio)
                                     if aircraft.bypass_ratio else None),
                    "noise_chapter": int(aircraft.noise_chapter),
                    "qa_status": overall,
                    "physics_crosscheck": json.dumps(
                        {k: round(float(v), 3) for k, v in crosscheck.items()}),
                    "created_utc": now,
                    "feature_schema": metadata.get("feature_schema"),
                    "training_population": metadata.get("training_population"),
                    "validation_report_sha256": metadata.get(
                        "validation_report_sha256"
                    ),
                }
                pd.DataFrame([ac_row]).to_sql("predicted_aircraft", conn,
                                              if_exists="append", index=False)
        return results

    # ---- read ------------------------------------------------------------
    def aircraft(self) -> pd.DataFrame:
        with contextlib.closing(self._conn()) as conn:
            return pd.read_sql_query("SELECT * FROM predicted_aircraft", conn)

    def npd(self, name: str | None = None,
            include_caution: bool = True) -> pd.DataFrame:
        q = "SELECT * FROM predicted_npd"
        clauses, args = [], []
        if name is not None:
            clauses.append("name = ?")
            args.append(name)
        if not include_caution:
            clauses.append("qa_status = 'ok'")
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        with contextlib.closing(self._conn()) as conn:
            return pd.read_sql_query(q, conn, params=args)
