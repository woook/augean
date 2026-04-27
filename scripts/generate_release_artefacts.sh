#!/usr/bin/env bash
# Generate release artefacts for filing in the CRMF.
#
# Produces:
#   requirements-hashed.txt  — fully pinned, hashed dependency list (DCB §7.1.3)
#   sbom.json                — CycloneDX SBOM of the installed environment (DSPT A4.a)
#
# Run from the repo root with the dev venv active:
#   source .venv/bin/activate
#   bash scripts/generate_release_artefacts.sh
#
# Both output files are gitignored. Download the relevant GitHub Actions
# artefact (release-artefacts-<sha>) from the CI run for the release commit
# and file alongside the CSCR in CRMF/evidence/release_configs/.

set -euo pipefail

echo "Generating hashed requirements..."
pip-compile pyproject.toml --generate-hashes --output-file requirements-hashed.txt
echo "  -> requirements-hashed.txt"

echo "Generating SBOM..."
cyclonedx-py environment --output-format json --outfile sbom.json
echo "  -> sbom.json"

echo ""
echo "Done. File these in CRMF/evidence/release_configs/ alongside the CSCR for this release."
