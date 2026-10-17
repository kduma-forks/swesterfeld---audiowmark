#!/usr/bin/env bash
# Build the technical manual once, out of tree, then install it into a staging root and publish verified PDF and HTML.
# Configure, build and install run from a separate build directory against a copy of the checkout.
# The copy is hashed after autoreconf and again after build and install: any write into the source copy fails the run.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${VERSION:?set VERSION}"
export LC_ALL=C.UTF-8 LANG=C.UTF-8
RELEASE_COMMIT=${RELEASE_COMMIT:-$(git -C "$ROOT" rev-parse HEAD)}
[[ $RELEASE_COMMIT =~ ^[0-9a-f]{40}$ ]] || { echo 'RELEASE_COMMIT must be a full commit hash' >&2; exit 1; }
SHORT_COMMIT=${RELEASE_COMMIT:0:12}
OUTPUT=${OUTPUT:-$ROOT/dist}
WORK=${DOCS_WORK:-$ROOT/.release/docs}
for tool in pandoc gnuplot xelatex dot python3 pdfinfo pdffonts pdftotext; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done

# Sorted sha256 of every regular file under a directory: a content fingerprint, independent of timestamps.
manifest() {
  (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum)
}

rm -rf "$WORK"
mkdir -p "$WORK/build" "$OUTPUT"
python3 - "$ROOT" "$WORK/project" <<'PY'
import pathlib, shutil, sys
root, destination = map(pathlib.Path, sys.argv[1:])
ignore = shutil.ignore_patterns('.git', '.context', '.release', 'dist', 'native', 'target', 'bin', 'obj', '__pycache__', 'autom4te.cache')
shutil.copytree(root, destination, ignore=ignore)
PY
(cd "$WORK/project" && autoreconf -fi)
manifest "$WORK/project" > "$WORK/project.before"

# --docdir pins the installed location so the staging check knows where the manual lands.
(cd "$WORK/build" && "$WORK/project/configure" --with-docs --docdir=/usr/share/doc/audiowmark \
  DOC_VERSION="$VERSION" DOC_COMMIT="$SHORT_COMMIT")
make -C "$WORK/build/docs" -j"${JOBS:-4}" audiowmark.pdf audiowmark.html
make -C "$WORK/build/docs" install DESTDIR="$WORK/install"

installed="$WORK/install/usr/share/doc/audiowmark"
for file in audiowmark.pdf audiowmark.html; do
  cmp "$installed/$file" "$WORK/build/docs/$file" || { echo "installed $file differs from build output" >&2; exit 1; }
done

manifest "$WORK/project" > "$WORK/project.after"
if ! cmp -s "$WORK/project.before" "$WORK/project.after"; then
  echo 'source copy changed during configure/build/install (out-of-tree violation):' >&2
  diff "$WORK/project.before" "$WORK/project.after" >&2 || true
  exit 1
fi

cp "$WORK/build/docs/audiowmark.pdf" "$OUTPUT/audiowmark-$VERSION-docs.pdf"
cp "$WORK/build/docs/audiowmark.html" "$OUTPUT/audiowmark-$VERSION-docs.html"

browser=()
if [[ -n ${DOCS_BROWSER:-} ]]; then browser=(--browser "$DOCS_BROWSER"); fi
python3 "$ROOT/scripts/release/test-docs.py" \
  --pdf "$OUTPUT/audiowmark-$VERSION-docs.pdf" \
  --html "$OUTPUT/audiowmark-$VERSION-docs.html" \
  --version "$VERSION" --commit "$SHORT_COMMIT" \
  --source "$WORK/project/docs/audiowmark.md" \
  --build-docs "$WORK/build/docs" "${browser[@]}"

# Verified documents are copies in OUTPUT. Clean the build tree and confirm that no generated or copied input is left behind.
make -C "$WORK/build/docs" clean
for path in audiowmark.pdf audiowmark.html graphviz-images example-spectrum.png example-spectrum.dat example-spectrum.gp; do
  [[ ! -e "$WORK/build/docs/$path" ]] || { echo "make clean left $path in the build directory" >&2; exit 1; }
done
[[ -f "$OUTPUT/audiowmark-$VERSION-docs.pdf" && -f "$OUTPUT/audiowmark-$VERSION-docs.html" ]] || {
  echo 'published documents are missing after make clean' >&2; exit 1; }
manifest "$WORK/project" > "$WORK/project.final"
if ! cmp -s "$WORK/project.before" "$WORK/project.final"; then
  echo 'source copy changed during the documentation build (clean included):' >&2
  diff "$WORK/project.before" "$WORK/project.final" >&2 || true
  exit 1
fi
echo "published $OUTPUT/audiowmark-$VERSION-docs.pdf and .html"
