#!/usr/bin/env bash
# Static checks for known footguns documented in CLAUDE.md §5.
# Runs in CI before tests; fails fast if any of the prior bugs sneaks
# back in via a new commit. Keeps the rule "no regression test → no
# fix" honest by encoding non-testable-via-unit-test invariants here.

set -euo pipefail
fail=0

echo "[check] middleware.ts vs proxy.ts coexistence (Next.js 16 OOM trap)"
if [ -f web-next/src/middleware.ts ] && [ -f web-next/src/proxy.ts ]; then
  echo "  ✗ Both web-next/src/middleware.ts AND web-next/src/proxy.ts exist."
  echo "    Next.js 16 rejects this with a 'workflow file issue' and the dev"
  echo "    server OOMs. Pick ONE — proxy.ts is the new name."
  fail=1
elif [ -f web-next/src/middleware.ts ]; then
  echo "  ✗ web-next/src/middleware.ts exists but Next.js 16 expects proxy.ts."
  fail=1
else
  echo "  ✓ proxy-only"
fi

echo "[check] job-level 'if: \${{ secrets.X != \"\" }}' in workflows (silent 0s fail)"
# GitHub Actions rejects secrets in job-level if conditions, killing the
# whole workflow file with a 0-second 'workflow file issue' before any job
# runs. Catch it by grepping the YAML.
if grep -rEn '^\s{4}if:.*secrets\.' .github/workflows/ 2>/dev/null; then
  echo "  ✗ secrets context referenced in a job-level 'if:' — move it to a step."
  fail=1
else
  echo "  ✓ no job-level secrets gating"
fi

echo "[check] PostgREST .in().order() without explicit .limit() (1000-row cap)"
# Patterns like .in("ticker", arr).order(...) silently cap at 1000 rows.
# Each such call MUST also include .limit() so the truncation is intentional.
hits=$(grep -rnP '\.in\([^)]+\)\.eq\([^)]+\)\.order' web-next/src --include="*.ts" --include="*.tsx" 2>/dev/null || true)
if [ -n "$hits" ]; then
  # Heuristic: lines containing both .in() and .order() but NOT .limit() within
  # 3 following lines are suspect. Print + warn but don't fail (false positives
  # are likely; this is awareness).
  echo "$hits" | while IFS= read -r line; do
    file=$(echo "$line" | cut -d: -f1)
    lineno=$(echo "$line" | cut -d: -f2)
    # Check next 5 lines for .limit(
    if ! awk -v start="$lineno" -v end="$((lineno + 5))" 'NR>=start && NR<=end' "$file" | grep -q '\.limit('; then
      echo "  ⚠ $file:$lineno — .in().order() without .limit() within 5 lines."
    fi
  done
fi
echo "  (informational — review manually if rows show)"

echo "[check] React 16 component purity — delegated to eslint (react-hooks/purity)"
echo "  (ESLint rule react-hooks/purity already catches Date.now()/Math.random()"
echo "   inside client component render. Running 'npm run lint' covers this.)"

echo "[check] Server module importing runtime non-component from 'use client'"
# Bug seen 2026-05-20 (ERROR 1025776953): app/(app)/watchlist/page.tsx
# imported groupColorClass (plain util) from group-manager-client.tsx
# which is "use client". Production Vercel runtime crashed; local dev
# tolerated. Static check now blocks this regression family.
py=""
# Probe python availability — `command -v python` can resolve to a stub
# (Windows MS Store) that errors on script invocation. Run a real --version
# probe to confirm execution actually works.
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" --version >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done
if [ -n "$py" ]; then
  if ! "$py" scripts/find_client_module_imports.py; then
    fail=1
  fi
else
  echo "  ⚠ python not available — skipping client-import audit"
fi

echo "[check] api/requirements.txt covers known us-analysis cold-start deps"
# 2026-05-25 incident: app.db.connection imports `from psycopg_pool import
# ConnectionPool` but api/requirements.txt only had `psycopg[binary]`. Vercel
# Python function crashed at import time before our handler ran → silent
# HTML 500 instead of JSON traceback. Append here when a new external
# import enters the us-analysis handler chain.
needed=("pandas" "numpy" "requests" "python-dateutil" "psycopg" "psycopg-pool")
missing=()
for pkg in "${needed[@]}"; do
  if ! grep -qiE "^[[:space:]]*${pkg}([[:space:]]|\[|>|<|=|~|$)" api/requirements.txt; then
    missing+=("${pkg}")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "  ✗ api/requirements.txt missing: ${missing[*]}"
  fail=1
else
  echo "  ✓ ${#needed[@]} known cold-start deps present"
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "Static pitfall check FAILED — fix the above before committing."
  exit 1
fi
echo
echo "All static pitfall checks passed."
