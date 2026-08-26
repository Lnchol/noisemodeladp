# EASA and ECAC source ledger

This ledger keeps the external provenance boundary separate from learned-model evidence. The files under `projects/pnmf/03_data` are source inputs and are not edited by datastore generation.

| Release | Source URL | Runtime role | SHA-256 recorded in |
| --- | --- | --- | --- |
| EASA ANP v2.3 | [EASA ANP data](https://www.easa.europa.eu/en/domains/environment/policy-support-and-research/aircraft-noise-and-performance-anp-data) | legacy merge base | `anp_meta.source_hashes` and `anp_dataset_manifest` |
| EASA ANP v6.3 | [EASA ANP data](https://www.easa.europa.eu/en/domains/environment/policy-support-and-research/aircraft-noise-and-performance-anp-data) | required supplement and Jet runtime source | `anp_meta.source_hashes` and `anp_dataset_manifest` |
| ECAC Doc 29 Volume 3 Part 1 | [official ECAC PDF](https://www.ecac-ceac.org/images/documents/ECAC-Doc_29_4th_edition_Dec_2016_Volume_3_Part_1.pdf) | interpolation/reference-case implementation authority | `outputs/doc29_reference_verification.json` when an official workbook is supplied |

The runtime manifest also records each source filename, release identity, logical table, merge key, duplicate policy, source URL, and SHA-256. The ANP v2.3 and v6.3 source files remain byte-for-byte authoritative; Jet filtering applies only to the rebuilt SQLite runtime.

The EASA provenance supports use as verified modelling data. It does not establish Extra Trees accuracy, unseen-family generalisation, uncertainty calibration, or certification validity. ECAC Volume 3 Part 1 is an implementation/reference-case check. It is not a real-aircraft measurement validation study.
