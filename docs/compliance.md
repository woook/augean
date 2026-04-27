# Augean — Compliance Report

**Date:** 2026-04-27
**Version reviewed:** branch `add-mnv-column-haemonc-v1` (commit `2671eda`)
**Basis:** Code and documentation review only. No live system access.

---

## Applicability Determination

| Standard | Verdict | Justification |
|---|---|---|
| **DCB0129** (Manufacturer) | **IN SCOPE** | Augean processes patient-linked genomic data (specimen IDs, R-codes, variant classifications) and its output feeds a downstream clinical staging database. ClinVar submission is handled by a separate downstream process outside this repo. CUH Bioinformatics developed the tool in-house; CUH is the Manufacturer. |
| **DCB0160** (Deployment) | **IN SCOPE** | CUH GLH deploys and operates Augean against real patient workbooks in a production clinical context. |
| **DSPT — Genomics CAF** | **IN SCOPE** | CUH is an NHS GLH operating under the NHS GMS; it is subject to the CAF-aligned DSPT (v8, 2025–26, deadline 30 June 2026). Augean is a system within that organisation's digital estate. |
| **DSPT — IT Supplier** | **OUT OF SCOPE** | CUH is the NHS organisation itself, not an external supplier. |
| **UK MDR / MHRA** | **FLAG — likely out of scope, confirm** | Augean extracts and stages pre-classified variants; it does not perform classification or generate clinical decisions. Most analogous to a LIMS data connector or submission client. The Trust's medical devices lead should formally confirm this is not a medical device under Rule 11 — see [UK MDR Flag](#uk-mdr-flag). |

---

## CAF Outcome Gap Analysis

### Objective A — Managing security risk

| CAF outcome | Status | Finding |
|---|---|---|
| **A1 — Governance** | ❌ Gap | No board-level accountability, no named security/IG owner for the tool, no documented security policy covering Augean. *Governance control.* |
| **A2 — Risk management** | ❌ Gap | No risk register, no documented risk assessment for the tool. Required for the mandatory DSPT audit outcome A2.a. *Governance control.* |
| **A3 — Asset management** | ❌ Gap | No software asset register. Augean is not listed anywhere as a named clinical system asset with an owner. *Governance control.* |
| **A4 — Supply chain** | ❌ Gap | Runtime dependencies declared in `pyproject.toml` without version hashes. No SBOM (CycloneDX or SPDX). No CVE scan output filed. `psycopg2-binary` is a binary wheel with no hash pinning. *Software + governance control.* |

**Proposed controls:**

| Control | Type | CAF outcome |
|---|---|---|
| Add `pip-audit` to CI; gate on zero known CVEs | Software | A4 |
| Pin all dependencies with hashes in a `requirements.txt` generated at release time | Software | A4 |
| Generate an SBOM with `cyclonedx-bom` and file in CRMF | Software + governance | A4 |
| Document Augean in the GLH risk register and IG asset register with a named owner | Governance | A1, A2, A3 |

---

### Objective B — Protecting against cyber attack

| CAF outcome | Status | Finding |
|---|---|---|
| **B2 — Identity and access control** | ⚠️ Partial | Database credentials stored in a JSON file (`db_credentials.json`) that is gitignored. The `augean_writer` role has narrow DB privileges (INSERT/UPDATE on two tables only), which is good. No application-level enforcement of file permissions, no key rotation mechanism, and no MFA at the application layer. Access is not reviewed or audited. |
| **B3 — Data security** | ⚠️ Partial | SQLAlchemy + psycopg2 used without an explicit TLS `sslmode` in the connection URL. Patient-linked variant data (specimen IDs, HGVSc strings) travels over this connection. No evidence of encryption at rest for the staging DB. Error CSVs written to `output_dir` contain workbook filenames, which carry specimen IDs. No check in the code that PII is absent from error logs. |
| **B4 — System security** | ❌ Gap | No SAST tool configured (no `bandit`, no `semgrep`). No dependency CVE scanning in CI. No hash-pinned dependencies. Python 3.12 used — currently supported, but no explicit upgrade policy documented. |
| **B5 — Resilience** | ⚠️ Partial | Skip-already-parsed idempotency guard is good. Per-workbook error handling prevents total batch failure. No documented RTT-critical fallback or break-glass procedure. No backup/recovery process for the staging DB documented. |
| **B6 — Staff awareness and training** | ❌ Gap | No operator competency records, no training documentation for those running Augean. *Governance control.* |

**Proposed controls:**

| Control | Type | CAF outcome |
|---|---|---|
| Add `sslmode=require` (or `verify-full`) to the SQLAlchemy connection URL | Software | B3 |
| Assert in CI that no specimen-ID-like pattern (`\d{9}-`) appears in log output or error CSVs | Software | B3 |
| Add `bandit` to CI; gate on zero high-severity findings | Software | B4 |
| Add `pip-audit` to CI; gate on zero known CVEs | Software | B4 |
| Enforce file permission `0600` on `db_credentials.json` in documentation and/or assert at startup | Software + governance | B2 |
| Document credential rotation schedule | Governance | B2 |
| Document operator training and competency requirements | Governance | B6 |

---

### Objective C — Detecting cyber security events

| CAF outcome | Status | Finding |
|---|---|---|
| **C1 — Security monitoring** | ⚠️ Partial | Operational logging exists throughout (`logging` module, structured at INFO/WARNING/DEBUG). However, there is no security audit log: no record of *who* ran the tool, *when*, on *which workbooks*, or *what was written to the database*. The `staging_workbooks` table provides partial traceability (workbook name, date, parse status) but not operator identity. Logs are written to stdout/stderr with no retention or tamper-protection mechanism. |
| **C2 — Proactive security event discovery** | ❌ Gap | No penetration testing, no vulnerability scanning pipeline, no threat intelligence process. *Governance control for the GLH; B4 CVE scanning addresses the software side.* |

**Proposed controls:**

| Control | Type | CAF outcome |
|---|---|---|
| Add operator identity (OS username, hostname) to the `staging_workbooks` row at insert time | Software | C1 |
| Document log retention policy; route stdout logs to a retained location (e.g. systemd journal, centralised log aggregator) | Governance | C1 |

---

### Objective D — Minimising the impact of incidents

| CAF outcome | Status | Finding |
|---|---|---|
| **D1 — Response and recovery** | ⚠️ Partial | Per-workbook error handling is solid: `mark_workbook_failed` records failures, error CSVs are generated, and failed workbooks are retried on next run. No documented incident response procedure for data integrity events (e.g. incorrect records in the staging DB, partial batch failure). |
| **D2 — Lessons learned** | ❌ Gap | No post-incident review process documented. *Governance control.* |

**Proposed controls:**

| Control | Type | CAF outcome |
|---|---|---|
| Document a data integrity incident response procedure: who is contacted, how incorrect staging DB records are identified and removed, what triggers a safety incident report | Governance | D1 |

---

### Objective E — Using and sharing information appropriately (NHS overlay)

| CAF outcome | Status | Finding |
|---|---|---|
| **E1 — Lawful basis** | ❌ Gap | No check in the tool that workbooks being processed have a confirmed lawful basis. The tool trusts the operator to supply valid workbooks. *Governance control — SOP must confirm lawful basis before submission.* |
| **E2 — Data subject rights / consent** | ❌ Gap | No consent verification built into the pipeline. Workbooks are processed without any programmatic check that the relevant consent (or legitimate interests basis) is in place for processing patient-linked variant data. *Governance control — SOP must confirm lawful basis before running the pipeline.* |
| **E3 — Direct care sharing** | ⚠️ Partial | Augean writes patient-linked variant data to the staging DB for use in the clinical pathway for which it was collected. The tool does not itself submit data to any external system — downstream submission is out of scope for this repo. The risk is that staging DB records could be read by a downstream process before the data has been appropriately reviewed. No programmatic gate restricts which downstream processes can read the staging table. *Governance control needed to define access to the staging DB.* |
| **E5 — Data quality** | ✅ Addressed | Structural, field, and cross-sheet validators run before any DB write. Schema mismatch detection prevents silent column loss. Normalisation is explicit and tested. `coerce_date_last_evaluated` mitigates common data quality defects. Golden-file acceptance tests verify end-to-end output. |

**Proposed controls:**

| Control | Type | CAF outcome |
|---|---|---|
| Add a pre-submission gate: a required consent/authorisation flag in the deployment config or as a CLI argument, preventing production DB writes without explicit confirmation | Software | E2, E3 |
| Document the IG governance process for patient data processing (consent/lawful basis confirmation, opt-out checking, authorisation before pipeline runs on live cases) | Governance | E1, E2, E3 |
| Define and document access controls on the staging DB (`testdirectory.inca`) to restrict which downstream processes and roles can read staged records | Governance | E3 |

---

## DSPT Evidence Mapping (Genomics CAF, v8)

Current cycle: **v8 (2025–26)**, final deadline **30 June 2026**.

The 8 mandatory audit outcomes for CUH as a Genomics organisation:

| DSPT outcome | CAF principle | Current status | Evidence available / Gap |
|---|---|---|---|
| **A2.a** Risk management process | A2 | ❌ Gap | No risk register or documented risk assessment exists for Augean. Must be created before audit. |
| **A4.a** Supply chain | A4 | ❌ Gap | No SBOM, no hashed `requirements.txt`, no CVE scan output. `pip-audit` + `cyclonedx-bom` would generate the required artefacts. |
| **B2.a** Identity verification, authentication and authorisation | B2 | ⚠️ Partial | Narrow DB role (`augean_writer`) is evidence of least privilege. Credential file gitignored. Gaps: no access review records, no credential rotation schedule, no operator identity in audit trail. |
| **B4.d** Vulnerability management | B4 | ❌ Gap | No SAST, no CVE scan, no hash-pinned dependencies. Adding `bandit` + `pip-audit` to CI would satisfy this outcome. |
| **C1.a** Monitoring coverage | C1 | ⚠️ Partial | Operational logging in place. Gaps: no operator identity recorded, no security event classification, no log retention or tamper-protection. The `staging_workbooks` table provides a partial audit trail. |
| **D1.a** Response plan | D1 | ⚠️ Partial | Per-workbook failure handling and error CSV output are good operational controls. Gap: no formal incident response procedure covering data integrity events (e.g. incorrect records in the staging DB, partial batch failures). |
| **E2.b** Consent | E2 | ❌ Gap | No consent verification in tool. Governance SOP must document the lawful basis and consent framework before this outcome can be asserted. |
| **E3.a** Using and sharing for direct care | E3 | ⚠️ Partial | Augean writes to a staging DB for downstream use in the clinical pathway for which data was collected. Downstream submission is out of scope for this repo. Governance control needed to define who can read the staging table and under what authorisation. |

**Current DSPT position:** 3 outcomes partially addressed, 5 gaps. The GLH cannot assert "Achieved" on mandatory outcomes for the current cycle without remediation.

---

## DCB Gap Analysis

### Intended-Use Statement (draft — requires CSO approval)

**Intended user:** NHS clinical bioinformatician (or equivalent technical staff) operating within an NHS Genomics Laboratory Hub, working under the supervision of HCPC-registered Clinical Scientists.

**Intended use:** Augean extracts variant classification data from NHS genomics laboratory interpretation workbooks (`.xlsx` format), validates and normalises that data against a format-specific configuration, and loads the resulting variant records into a PostgreSQL staging database. It operates as a data pipeline tool between the laboratory's workbook-based classification workflow and a staging database. Downstream use of the staging database — including any submission to external systems — is outside the scope of this tool.

**Input:** Microsoft Excel workbooks produced by NHS genomics laboratory pipelines (currently: HaemOnc Uranus somatic workbooks generated by `eggd_generate_variant_workbook`, and RD Dias germline workbooks). Each workbook contains pre-classified variant records reviewed and approved by HCPC-registered Clinical Scientists.

**Output:** Rows inserted into a PostgreSQL staging table (`testdirectory.inca`). These rows carry variant classifications, HGVS nomenclature, sample metadata, and clinical indication data. Downstream use of this table is outside the scope of this tool.

**Not intended for:**
- Performing or influencing variant classification — Augean extracts classifications already made by Clinical Scientists
- Use outside an NHS GLH context
- Processing workbooks not produced by the supported pipeline versions
- Use by clinicians or clinical scientists as a direct clinical decision tool
- RD Dias workbooks in their current form (non-functional; not validated against the live DB schema — do not use in production)

---

### Seed Hazard Log

| Ref | Cause | Hazard | Patient effect | Indicative severity | Existing controls |
|---|---|---|---|---|---|
| H1 | Workbook filename shared between two patients (e.g. re-used sample ID) | Duplicate basename guard triggers `SystemExit` before any workbook is processed | Batch aborted; no variants staged for either patient | Significant | `SystemExit` on duplicate basename; documented in README |
| H2 | Normalisation maps an uncommon free-text classification value to an incorrect canonical term | Variant classification altered silently before staging | Incorrect classification staged; downstream processes act on wrong value | Considerable | Validator runs on raw values before normalisation; unit tests for all normalisation paths; in-list field validation |
| H3 | Workbook renamed between runs; skip-already-parsed keyed on basename | Previously processed workbook re-submitted under new filename | Duplicate variant records for the same patient case in the staging DB | Considerable | `ON CONFLICT DO NOTHING` on `inca_workbooks`; within-run deduplication via skip-set |
| H4 | Two workbook formats share identical fingerprint cells | Wrong config applied silently to workbook | Incorrect field mapping; wrong data extracted and staged | Major | Ambiguous-match error if two configs match; fingerprint requires multiple cell checks |
| H5 | `--migrate` auto-adds a column with wrong inferred type | Data inserted into incorrectly-typed column | Silent data truncation or type coercion; incorrect values in staging DB | Considerable | `--migrate` is opt-in; WARNING logged per column added; default raises `SchemaMismatchError` |
| H6 | Database credential file (`db_credentials.json`) readable by other OS users | Unauthorised party writes arbitrary data to staging DB | Incorrect or malicious variant records associated with patient referrals | Major | File gitignored; `augean_writer` has narrow DB privileges; no application-level permission enforcement |
| H7 | Partial batch failure: some workbooks succeed, others fail, with no atomic transaction across the batch | Staging DB contains a partial subset of the intended batch | Incomplete set of records available to downstream processes; uncertainty about which patients are covered | Considerable | Per-workbook `mark_workbook_failed`; error CSV written; failed workbooks retried on next run |

---

### Control Mapping (DCB0129 §6 hierarchy)

| Ref | Control level | Controls |
|---|---|---|
| H1 | Level 2 — Protective/automated | Duplicate basename check raises `SystemExit` before processing loop begins |
| H2 | Level 2 — Protective/automated | Pre-normalisation validation; unit + acceptance tests covering all normalisation branches |
| H3 | Level 2 + Level 3 | `ON CONFLICT DO NOTHING`; within-run skip-set; **gap: no cross-run deduplication on content hash** |
| H4 | Level 2 — Protective/automated | Multi-cell fingerprint matching; ambiguous-match error if multiple configs match |
| H5 | Level 2 + Level 3 | Default `SchemaMismatchError` (protective); `--migrate` is opt-in with WARNING logging (information for safety) |
| H6 | Level 3 — Information for safety | `.gitignore`; documentation recommends narrow DB role. **Gap: no OS permission enforcement, no rotation schedule** |
| H7 | Level 2 — Protective/automated | Per-workbook isolation; `mark_workbook_failed`; error CSV; retry on next run |

---

### Residual Risks

| Ref | Residual risk | Action required |
|---|---|---|
| H2 | Unknown classification alias variants not covered by tests | DCB0129 §6.2 — CSO sign-off on accepted residual; future work: exhaustive alias registry |
| H3 | Workbook rename bypasses skip-already-parsed | Future software item: content-hash deduplication as secondary guard |
| H6 | OS-level credential file permissions not enforced by application | DCB0160 deployment-side control: SOPs for credential management; periodic access review |

---

### DCB0160 Deployment Obligations

The following fall on CUH GLH as the Health Organisation deploying Augean:

| Obligation | Status | Notes |
|---|---|---|
| **Top Management authorisation per release** | ❌ Not evidenced | A named clinical executive (Medical Director or CCIO) must sign off each release in writing before clinical use. A blanket authorisation is insufficient. |
| **Competency records per operator** | ❌ Not evidenced | Required per staff member, per workbook format, with a defined re-competency cadence. |
| **Local customisations under change control** | ❌ Not evidenced | Deployment configs (`deployment.json`) and any local scripts that reshape data before ingestion must be under change control with a clinical owner and review date. |
| Named Deployment CSO (independent from dev team) | ❌ Not evidenced | Must be a registered clinician; should be independent from the development team where possible. |
| Three scope statements in deployment CRMP | ❌ Not evidenced | Clinical scope, intended use, operational environment and users (DCB0160 §4.2). |
| User training environment with synthetic data | ❌ Not evidenced | Operators must not use live patient workbooks for training runs. The `--dry_run` flag supports this but a synthetic-data environment should be documented. |
| Incident reporting channel and CSO triage | ❌ Not evidenced | Joint triage channel with the development team required. |
| Decommissioning plan | ❌ Not evidenced | Must cover: classification provenance retention, audit trail continuity, cascade-testing implications for relatives. |

---

### CRMF Artefact Checklist

**Governance:**
- [ ] Named CSO (HCPC/GMC/NMC registered, CRM-trained) with ring-fenced time
- [ ] Named CSO deputy
- [ ] Top Management resource commitment documented

**Per-product documents:**
- [ ] CRMP approved by CSO; explicit risk acceptability matrix (5×5 or equivalent)
- [x] Intended-use statement — draft in this document; requires CSO approval
- [x] Seed hazard log — in this document; requires formalisation and CSO approval

**Third-party evidence:**
- [ ] Third-party component register: all deps in safety-relevant paths, with versions, source, and role
- [ ] `requirements.txt` with hashes (per release) — can be generated: `pip install -r requirements.txt --dry-run --report`
- [ ] SBOM (CycloneDX JSON) — `cyclonedx-bom` can generate from the venv
- [ ] CVE scan output per release — `pip-audit` output; file alongside each CSCR

**Per-release:**
- [ ] Clinical Safety Case Report (CSCR), CSO-signed, before clinical use
- [x] CI test suite output — tests exist and pass (164 passing, 96% coverage); output not yet filed as formal DCB §6.3 verification evidence
- [ ] Complete dependency version record in CSCR (all resolved transitive deps)
- [ ] Change log: changes since last CSCR; classification of each change by safety impact

**Ongoing:**
- [ ] Safety Incident Management Log with defined reporting channel and CSO triage process
- [ ] Quarterly CRM process review (§2.6); minutes filed in CRMF
- [ ] Post-deployment monitoring plan

Items where **existing repo content directly contributes:**
- `README.md`, `docs/architecture.md`, `docs/config-guide.md` → third-party register (partially) and intended-use evidence
- `pytest` CI output → §6.3 verification evidence (if CI archives artefacts per release)
- `.gitignore` and `db_credentials.template.json` → credential management evidence for B2/B3

---

## UK MDR Flag

**Augean is likely not a medical device** under UK MDR 2002 (as amended). It functions as a data extraction and staging tool, not a clinical decision support system — variant classifications are made by HCPC-registered Clinical Scientists in Excel workbooks before Augean processes them. Augean does not suggest, modify, or override these classifications; it extracts them. The normalisation steps (e.g. `VUS` → `Uncertain significance`) are lexical standardisation of free-text entries to canonical forms, not clinical judgements.

However: if future development adds any logic that influences which variants are submitted, flags variants for review, or makes any classification determination, the MDR position must be reassessed. Recommend the Trust's medical devices / MHRA liaison lead reviews this assessment and formally confirms the position before first production use. DCB0129 compliance supports but does not substitute for MHRA registration if the position changes.

---

## Priority Actions

### Immediate (before first production use / v1.0.0 clinical release)

1. **Name a CSO** and get Top Management commitment documented — blocks all DCB artefacts
2. **Formalise the CRMF** using the seed hazard log and intended-use statement above as starting points; get CSO approval
3. **Address H6** — enforce OS-level credential file permissions or document the mitigating SOP
4. **Add `pip-audit` and `bandit` to CI** — directly satisfies B4.d (mandatory DSPT audit outcome)
5. **Add TLS enforcement to the DB connection** (`sslmode=require`)

### Short-term (before DSPT v8 final submission, 30 June 2026)

6. Add operator identity to the `staging_workbooks` table for C1 audit logging
7. Generate and file an SBOM and hashed `requirements.txt` per release for A4.a
8. Document credential rotation, access review, and operator competency records for B2.a and D1.a
9. Write a data integrity incident response procedure for D1.a
10. Write the IG governance SOP for patient data processing and staging DB access controls (consent/lawful basis, opt-out checking, authorised readers of `testdirectory.inca`) for E2.b and E3.a
