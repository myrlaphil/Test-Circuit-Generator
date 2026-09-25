#!/usr/bin/env bash
# Assemble the GitHub Pages build (stlite: Streamlit running in the browser) into _site/.
# Used by .github/workflows/pages.yml and for local testing:  bash build_site.sh && python3 -m http.server -d _site 8765
set -euo pipefail
cd "$(dirname "$0")"
rm -rf _site && mkdir -p _site
cp site/index.html _site/
cp app.py lingo.py render_worker.py exam_pdf.py llm.py circuit_core.py _site/
touch _site/.nojekyll
echo "built _site/ with: $(ls _site | tr '\n' ' ')"
