#!/usr/bin/env bash
#
# release.sh — Package and optionally upload GeoLineage QGIS plugin
#
# Usage:
#   ./scripts/release.sh              # Build ZIP only
#   ./scripts/release.sh --upload     # Build ZIP and create GitHub release
#   ./scripts/release.sh --draft      # Build ZIP and create draft GitHub release
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_NAME="GeoLineage"

# Read version from metadata.txt
VERSION=$(grep -E '^version=' "$PROJECT_DIR/metadata.txt" | cut -d= -f2 | tr -d '[:space:]')
if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not read version from metadata.txt"
    exit 1
fi

TAG="v${VERSION}"
ZIP_NAME="${PLUGIN_NAME}-${VERSION}.zip"
BUILD_DIR="$PROJECT_DIR/build"

echo "=== GeoLineage Release Script ==="
echo "Version: $VERSION"
echo "Tag:     $TAG"
echo "Output:  $BUILD_DIR/$ZIP_NAME"
echo ""

# --- Validation ---

echo "Validating plugin structure..."

# Required files
for f in metadata.txt __init__.py plugin.py LICENSE; do
    if [[ ! -f "$PROJECT_DIR/$f" ]]; then
        echo "ERROR: Required file missing: $f"
        exit 1
    fi
done

# Validate metadata.txt has all required fields
for field in name qgisMinimumVersion description about version author email repository; do
    if ! grep -qE "^${field}=" "$PROJECT_DIR/metadata.txt"; then
        echo "ERROR: Required metadata field missing: $field"
        exit 1
    fi
done

# Validate icon exists
ICON=$(grep -E '^icon=' "$PROJECT_DIR/metadata.txt" | cut -d= -f2 | tr -d '[:space:]')
if [[ -n "$ICON" && ! -f "$PROJECT_DIR/$ICON" ]]; then
    echo "ERROR: Icon file not found: $ICON"
    exit 1
fi

# Check for syntax errors in Python files
echo "Checking Python syntax..."
SYNTAX_OK=true
while IFS= read -r -d '' pyfile; do
    if ! python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>/dev/null; then
        echo "  SYNTAX ERROR: $pyfile"
        SYNTAX_OK=false
    fi
done < <(find "$PROJECT_DIR" -maxdepth 1 -name "*.py" -print0)
while IFS= read -r -d '' pyfile; do
    if ! python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>/dev/null; then
        echo "  SYNTAX ERROR: $pyfile"
        SYNTAX_OK=false
    fi
done < <(find "$PROJECT_DIR/lineage_core" "$PROJECT_DIR/lineage_retrieval" -name "*.py" -print0)

if [[ "$SYNTAX_OK" != "true" ]]; then
    echo "ERROR: Python syntax errors found. Fix before releasing."
    exit 1
fi
echo "  All Python files OK"

echo "Validation passed."
echo ""

# --- Build ZIP ---

echo "Building plugin ZIP..."

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/$PLUGIN_NAME"

# Copy plugin files into build directory
# Top-level files
cp "$PROJECT_DIR/metadata.txt" "$BUILD_DIR/$PLUGIN_NAME/"
cp "$PROJECT_DIR/__init__.py" "$BUILD_DIR/$PLUGIN_NAME/"
cp "$PROJECT_DIR/plugin.py" "$BUILD_DIR/$PLUGIN_NAME/"
cp "$PROJECT_DIR/LICENSE" "$BUILD_DIR/$PLUGIN_NAME/"
cp "$PROJECT_DIR/README.md" "$BUILD_DIR/$PLUGIN_NAME/"

# Python packages
for pkg in lineage_core lineage_retrieval; do
    mkdir -p "$BUILD_DIR/$PLUGIN_NAME/$pkg"
    find "$PROJECT_DIR/$pkg" -name "*.py" ! -path "*__pycache__*" -exec cp {} "$BUILD_DIR/$PLUGIN_NAME/$pkg/" \;
done

# Resources
if [[ -d "$PROJECT_DIR/resources" ]]; then
    cp -r "$PROJECT_DIR/resources" "$BUILD_DIR/$PLUGIN_NAME/resources"
fi

# Create ZIP (from build dir so paths are relative)
cd "$BUILD_DIR"
zip -r "$ZIP_NAME" "$PLUGIN_NAME/" -x "*__pycache__*" "*.pyc"
cd "$PROJECT_DIR"

ZIP_SIZE=$(du -h "$BUILD_DIR/$ZIP_NAME" | cut -f1)
echo "  Created: $BUILD_DIR/$ZIP_NAME ($ZIP_SIZE)"
echo ""

# --- List ZIP contents ---
echo "ZIP contents:"
unzip -l "$BUILD_DIR/$ZIP_NAME" | tail -n +4 | head -n -2 | awk '{print "  " $4}'
echo ""

# --- Upload to GitHub ---

ACTION="none"
for arg in "$@"; do
    case "$arg" in
        --upload) ACTION="upload" ;;
        --draft)  ACTION="draft" ;;
    esac
done

if [[ "$ACTION" == "none" ]]; then
    echo "ZIP ready. To upload to GitHub:"
    echo "  ./scripts/release.sh --upload    # Create public release"
    echo "  ./scripts/release.sh --draft     # Create draft release"
    exit 0
fi

# Check gh CLI is available
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI (gh) is not installed."
    echo "Install: https://cli.github.com/"
    exit 1
fi

# Check authentication
if ! gh auth status &>/dev/null; then
    echo "ERROR: Not authenticated with GitHub CLI. Run: gh auth login"
    exit 1
fi

# Check if tag already exists on remote
if git ls-remote --tags origin | grep -q "refs/tags/$TAG$"; then
    echo "ERROR: Tag $TAG already exists on remote. Bump version in metadata.txt first."
    exit 1
fi

# Create git tag
if ! git tag -l "$TAG" | grep -q "$TAG"; then
    echo "Creating git tag: $TAG"
    git tag -a "$TAG" -m "Release $TAG"
fi

echo "Pushing tag to origin..."
git push origin "$TAG"

# Build release notes from changelog in metadata.txt
CHANGELOG=$(grep -A 100 '^changelog=' "$PROJECT_DIR/metadata.txt" | head -1 | cut -d= -f2-)
NOTES="## GeoLineage $TAG

${CHANGELOG:-Initial release.}

### Installation

1. Download \`$ZIP_NAME\` below
2. In QGIS: **Plugins > Manage and Install Plugins > Install from ZIP**
3. Select the downloaded ZIP and click **Install Plugin**

### Requirements

- QGIS 3.34 LTS or later"

DRAFT_FLAG=""
if [[ "$ACTION" == "draft" ]]; then
    DRAFT_FLAG="--draft"
    echo "Creating DRAFT GitHub release..."
else
    echo "Creating GitHub release..."
fi

gh release create "$TAG" \
    "$BUILD_DIR/$ZIP_NAME#$ZIP_NAME" \
    --title "GeoLineage $TAG" \
    --notes "$NOTES" \
    --target main \
    $DRAFT_FLAG

echo ""
echo "Release created successfully!"
echo "URL: $(gh release view "$TAG" --json url -q '.url')"
