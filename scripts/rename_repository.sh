#!/bin/bash

# Repository Name Change Script
# Changes from "unified-mcp-server"/"unified_mcp_server" to "ai-intelligence-mcp-server"/"ai_intelligence_mcp_server"

set -e  # Exit on any error

echo "🚀 Starting repository name change process..."

# Define the new names
OLD_NAME_HYPHEN="unified-mcp-server"
NEW_NAME_HYPHEN="ai-intelligence-mcp-server"
OLD_NAME_UNDERSCORE="unified_mcp_server"
NEW_NAME_UNDERSCORE="ai_intelligence_mcp_server"
OLD_TITLE="Unified MCP Intelligence Server"
NEW_TITLE="AI Intelligence MCP Server"
OLD_DESC="Production-ready unified MCP server abstracting Qdrant, Neo4j, and Crawl4AI"
NEW_DESC="Advanced AI Intelligence MCP server combining vector search, knowledge graphs, and web intelligence"

# Backup current state
echo "📦 Creating backup..."
cp -r . ../backup-$(date +%Y%m%d-%H%M%S) 2>/dev/null || echo "Backup skipped (optional)"

# Phase 1: Rename Python package directory
echo "📁 Renaming Python package directory..."
if [ -d "src/$OLD_NAME_UNDERSCORE" ]; then
    mv "src/$OLD_NAME_UNDERSCORE" "src/$NEW_NAME_UNDERSCORE"
    echo "✅ Renamed src/$OLD_NAME_UNDERSCORE to src/$NEW_NAME_UNDERSCORE"
else
    echo "⚠️ Directory src/$OLD_NAME_UNDERSCORE not found"
fi

# Phase 2: Update all Python import statements
echo "🐍 Updating Python import statements..."
find . -name "*.py" -type f -exec sed -i "s/$OLD_NAME_UNDERSCORE/$NEW_NAME_UNDERSCORE/g" {} +
echo "✅ Updated Python imports"

# Phase 3: Update pyproject.toml
echo "📝 Updating pyproject.toml..."
sed -i "s/name = \"$OLD_NAME_HYPHEN\"/name = \"$NEW_NAME_HYPHEN\"/g" pyproject.toml
sed -i "s|$OLD_DESC|$NEW_DESC|g" pyproject.toml
echo "✅ Updated pyproject.toml"

# Phase 4: Update README.md
echo "📖 Updating README.md..."
sed -i "s/$OLD_TITLE/$NEW_TITLE/g" README.md
sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" README.md
sed -i "s/mcp-unified-intelligence/$NEW_NAME_HYPHEN/g" README.md
sed -i "s/cd mcp-unified-intelligence/cd $NEW_NAME_HYPHEN/g" README.md
echo "✅ Updated README.md"

# Phase 5: Update documentation files
echo "📚 Updating documentation files..."
find docs/ -name "*.md" -type f -exec sed -i "s/$OLD_TITLE/$NEW_TITLE/g" {} + 2>/dev/null || echo "No docs/ directory"
find docs/ -name "*.md" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} + 2>/dev/null || echo "No docs/ directory"

# Update PORTFOLIO_SUMMARY.md
if [ -f "PORTFOLIO_SUMMARY.md" ]; then
    sed -i "s/$OLD_TITLE/$NEW_TITLE/g" PORTFOLIO_SUMMARY.md
    sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" PORTFOLIO_SUMMARY.md
    sed -i "s/unified-mcp-server/$NEW_NAME_HYPHEN/g" PORTFOLIO_SUMMARY.md
    echo "✅ Updated PORTFOLIO_SUMMARY.md"
fi

# Phase 6: Update Docker files
echo "🐳 Updating Docker configuration..."
sed -i "s/Unified MCP Server/$NEW_TITLE/g" Dockerfile
sed -i "s/$OLD_DESC/$NEW_DESC/g" Dockerfile

# Update docker-compose files
for file in docker-compose.yml docker-compose.prod.yml; do
    if [ -f "$file" ]; then
        sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" "$file"
        echo "✅ Updated $file"
    fi
done

# Phase 7: Update Kubernetes manifests
echo "☸️ Updating Kubernetes manifests..."
if [ -d "k8s/manifests" ]; then
    find k8s/manifests/ -name "*.yaml" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} +
    
    # Rename the main manifest file
    if [ -f "k8s/manifests/unified-mcp-server.yaml" ]; then
        mv "k8s/manifests/unified-mcp-server.yaml" "k8s/manifests/$NEW_NAME_HYPHEN.yaml"
        echo "✅ Renamed Kubernetes manifest file"
    fi
    echo "✅ Updated Kubernetes manifests"
fi

# Phase 8: Update CI/CD workflows
echo "🔄 Updating CI/CD workflows..."
if [ -d ".github/workflows" ]; then
    find .github/workflows/ -name "*.yml" -type f -exec sed -i "s/$OLD_TITLE/$NEW_TITLE/g" {} +
    find .github/workflows/ -name "*.yml" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} +
    echo "✅ Updated GitHub Actions workflows"
fi

# Phase 9: Update deployment configurations
echo "🚀 Updating deployment configurations..."

# Railway
if [ -f "deployment/railway.json" ]; then
    sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" deployment/railway.json
    sed -i "s|$OLD_DESC|$NEW_DESC|g" deployment/railway.json
    echo "✅ Updated Railway configuration"
fi

# Fly.io
if [ -f "deployment/fly.toml" ]; then
    sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" deployment/fly.toml
    echo "✅ Updated Fly.io configuration"
fi

# Phase 10: Update monitoring configurations
echo "📊 Updating monitoring configurations..."
if [ -d "monitoring" ]; then
    find monitoring/ -name "*.json" -type f -exec sed -i "s/$OLD_TITLE/$NEW_TITLE/g" {} +
    find monitoring/ -name "*.json" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} +
    find monitoring/ -name "*.yml" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} +
    echo "✅ Updated monitoring configurations"
fi

# Phase 11: Update environment template
echo "🔧 Updating environment configuration..."
if [ -f ".env.template" ]; then
    sed -i "s/Unified MCP Server/$NEW_TITLE/g" .env.template
    echo "✅ Updated .env.template"
fi

# Phase 12: Update logs and research files
echo "📝 Updating logs and research files..."
if [ -d "logs" ]; then
    find logs/ -name "*.md" -type f -exec sed -i "s/$OLD_TITLE/$NEW_TITLE/g" {} +
    find logs/ -name "*.md" -type f -exec sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" {} +
    echo "✅ Updated log files"
fi

# Phase 13: Update deployment script
echo "📜 Updating deployment script..."
if [ -f "scripts/deploy.sh" ]; then
    sed -i "s/$OLD_NAME_HYPHEN/$NEW_NAME_HYPHEN/g" scripts/deploy.sh
    echo "✅ Updated deploy.sh"
fi

# Phase 14: Run final formatting
echo "🎨 Running final code formatting..."
if command -v ruff &> /dev/null; then
    ruff format . 2>/dev/null || echo "Ruff formatting skipped"
    ruff check . --fix 2>/dev/null || echo "Ruff linting skipped"
fi

# Summary
echo ""
echo "🎉 Repository name change completed successfully!"
echo ""
echo "📋 Summary of changes:"
echo "  • Package name: $OLD_NAME_HYPHEN → $NEW_NAME_HYPHEN"
echo "  • Module name: $OLD_NAME_UNDERSCORE → $NEW_NAME_UNDERSCORE"
echo "  • Project title: $OLD_TITLE → $NEW_TITLE"
echo "  • Updated: Python imports, Docker configs, K8s manifests, CI/CD, docs"
echo ""
echo "🔄 Next steps:"
echo "  1. Review changes: git diff"
echo "  2. Test the application: uv run python -m $NEW_NAME_UNDERSCORE"
echo "  3. Run tests: uv run pytest"
echo "  4. Commit changes: git add . && git commit -m 'Rename repository to $NEW_NAME_HYPHEN'"
echo "  5. Update GitHub repository name in settings"
echo "  6. Update remote URL: git remote set-url origin https://github.com/username/$NEW_NAME_HYPHEN.git"
echo ""
echo "✅ Repository rename complete!"