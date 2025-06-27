#!/bin/bash
# Qdrant Neo4j Crawl4AI MCP Server Deployment Script
# Production-ready deployment automation with validation and rollback

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/tmp/qdrant-neo4j-crawl4ai-mcp-deploy_${TIMESTAMP}.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
ENVIRONMENT="${ENVIRONMENT:-production}"
NAMESPACE="${NAMESPACE:-qdrant-neo4j-crawl4ai-mcp}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY="${REGISTRY:-ghcr.io/your-username}"
DRY_RUN="${DRY_RUN:-false}"
SKIP_TESTS="${SKIP_TESTS:-false}"
FORCE_DEPLOY="${FORCE_DEPLOY:-false}"
BACKUP_BEFORE_DEPLOY="${BACKUP_BEFORE_DEPLOY:-true}"
ENABLE_MONITORING="${ENABLE_MONITORING:-true}"

# Logging functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $*${NC}" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $*${NC}" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*${NC}" | tee -a "$LOG_FILE"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] INFO: $*${NC}" | tee -a "$LOG_FILE"
}

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Deploy Qdrant Neo4j Crawl4AI MCP Server to Kubernetes

OPTIONS:
    -e, --environment ENV       Deployment environment (development|staging|production) [default: production]
    -n, --namespace NAMESPACE   Kubernetes namespace [default: qdrant-neo4j-crawl4ai-mcp]
    -t, --tag TAG              Docker image tag [default: latest]
    -r, --registry REGISTRY    Container registry [default: ghcr.io/your-username]
    -d, --dry-run              Show what would be deployed without making changes [default: false]
    -s, --skip-tests           Skip pre-deployment tests [default: false]
    -f, --force                Force deployment even if validation fails [default: false]
    -b, --no-backup            Skip backup before deployment [default: false]
    -m, --no-monitoring        Skip monitoring stack deployment [default: false]
    -h, --help                 Show this help message

EXAMPLES:
    # Deploy to production with latest tag
    $0 --environment production --tag v1.2.3

    # Dry run deployment to staging
    $0 --environment staging --dry-run

    # Force deployment without backup
    $0 --force --no-backup

ENVIRONMENT VARIABLES:
    KUBECONFIG                 Path to kubeconfig file
    GITHUB_TOKEN              GitHub token for image registry access
    BACKUP_S3_BUCKET          S3 bucket for backups
    SLACK_WEBHOOK_URL         Slack webhook for notifications

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -n|--namespace)
                NAMESPACE="$2"
                shift 2
                ;;
            -t|--tag)
                IMAGE_TAG="$2"
                shift 2
                ;;
            -r|--registry)
                REGISTRY="$2"
                shift 2
                ;;
            -d|--dry-run)
                DRY_RUN="true"
                shift
                ;;
            -s|--skip-tests)
                SKIP_TESTS="true"
                shift
                ;;
            -f|--force)
                FORCE_DEPLOY="true"
                shift
                ;;
            -b|--no-backup)
                BACKUP_BEFORE_DEPLOY="false"
                shift
                ;;
            -m|--no-monitoring)
                ENABLE_MONITORING="false"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done
}

# Validate environment
validate_environment() {
    log "Validating deployment environment..."
    
    # Check required tools
    local required_tools=("kubectl" "docker" "helm")
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            error "$tool is required but not installed"
        fi
    done
    
    # Validate environment parameter
    if [[ ! "$ENVIRONMENT" =~ ^(development|staging|production)$ ]]; then
        error "Invalid environment: $ENVIRONMENT. Must be development, staging, or production"
    fi
    
    # Check Kubernetes connection
    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster. Check your kubeconfig"
    fi
    
    # Check namespace exists or can be created
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        warn "Namespace $NAMESPACE does not exist. It will be created."
    fi
    
    # Validate image tag format
    if [[ ! "$IMAGE_TAG" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        error "Invalid image tag format: $IMAGE_TAG"
    fi
    
    log "Environment validation completed successfully"
}

# Pre-deployment checks
pre_deployment_checks() {
    log "Running pre-deployment checks..."
    
    # Check if previous deployment exists
    if kubectl get deployment qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE" &> /dev/null; then
        info "Previous deployment found. Will perform rolling update."
    else
        info "No previous deployment found. Will perform fresh deployment."
    fi
    
    # Check resource quotas
    local cpu_requests=$(kubectl describe quota -n "$NAMESPACE" 2>/dev/null | grep "requests.cpu" | awk '{print $2}' || echo "0")
    local memory_requests=$(kubectl describe quota -n "$NAMESPACE" 2>/dev/null | grep "requests.memory" | awk '{print $2}' || echo "0")
    
    if [[ "$cpu_requests" != "0" ]] || [[ "$memory_requests" != "0" ]]; then
        info "Resource quotas detected: CPU=$cpu_requests, Memory=$memory_requests"
    fi
    
    # Check persistent volumes
    local pv_count=$(kubectl get pv -o jsonpath='{.items[?(@.spec.claimRef.namespace=="'$NAMESPACE'")].metadata.name}' | wc -w)
    if [[ "$pv_count" -gt 0 ]]; then
        info "Found $pv_count persistent volumes in namespace $NAMESPACE"
    fi
    
    log "Pre-deployment checks completed"
}

# Run tests
run_tests() {
    if [[ "$SKIP_TESTS" == "true" ]]; then
        warn "Skipping tests as requested"
        return 0
    fi
    
    log "Running pre-deployment tests..."
    
    # Container security scan
    if command -v trivy &> /dev/null; then
        info "Running container security scan..."
        if ! trivy image --exit-code 0 --severity HIGH,CRITICAL "$REGISTRY/qdrant-neo4j-crawl4ai-mcp:$IMAGE_TAG"; then
            if [[ "$FORCE_DEPLOY" != "true" ]]; then
                error "Security scan failed. Use --force to deploy anyway"
            else
                warn "Security scan failed but continuing due to --force flag"
            fi
        fi
    else
        warn "Trivy not found, skipping container security scan"
    fi
    
    # Kubernetes manifest validation
    info "Validating Kubernetes manifests..."
    if ! kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/" &> /dev/null; then
        error "Kubernetes manifest validation failed"
    fi
    
    # Check image availability
    info "Checking image availability..."
    if ! docker manifest inspect "$REGISTRY/qdrant-neo4j-crawl4ai-mcp:$IMAGE_TAG" &> /dev/null; then
        if [[ "$FORCE_DEPLOY" != "true" ]]; then
            error "Image $REGISTRY/qdrant-neo4j-crawl4ai-mcp:$IMAGE_TAG not found. Use --force to deploy anyway"
        else
            warn "Image not found but continuing due to --force flag"
        fi
    fi
    
    log "Tests completed successfully"
}

# Backup current deployment
backup_deployment() {
    if [[ "$BACKUP_BEFORE_DEPLOY" != "true" ]]; then
        warn "Skipping backup as requested"
        return 0
    fi
    
    log "Creating backup of current deployment..."
    
    local backup_dir="/tmp/qdrant-neo4j-crawl4ai-mcp-backup_${TIMESTAMP}"
    mkdir -p "$backup_dir"
    
    # Backup Kubernetes resources
    info "Backing up Kubernetes resources..."
    kubectl get all,configmaps,secrets,pvc,ingress -n "$NAMESPACE" -o yaml > "$backup_dir/kubernetes-resources.yaml" 2>/dev/null || true
    
    # Backup database data (if applicable)
    if kubectl get pod -l app.kubernetes.io/name=qdrant -n "$NAMESPACE" &> /dev/null; then
        info "Creating Qdrant snapshot..."
        kubectl exec -n "$NAMESPACE" deployment/qdrant -- curl -X POST "http://localhost:6333/collections/qdrant_neo4j_crawl4ai_intelligence/snapshots" || warn "Failed to create Qdrant snapshot"
    fi
    
    # Compress backup
    tar -czf "/tmp/qdrant-neo4j-crawl4ai-mcp-backup_${TIMESTAMP}.tar.gz" -C "/tmp" "qdrant-neo4j-crawl4ai-mcp-backup_${TIMESTAMP}"
    rm -rf "$backup_dir"
    
    # Upload to S3 if configured
    if [[ -n "${BACKUP_S3_BUCKET:-}" ]]; then
        info "Uploading backup to S3..."
        aws s3 cp "/tmp/qdrant-neo4j-crawl4ai-mcp-backup_${TIMESTAMP}.tar.gz" "s3://$BACKUP_S3_BUCKET/qdrant-neo4j-crawl4ai-mcp-backups/" || warn "Failed to upload backup to S3"
    fi
    
    log "Backup completed: /tmp/qdrant-neo4j-crawl4ai-mcp-backup_${TIMESTAMP}.tar.gz"
}

# Deploy infrastructure
deploy_infrastructure() {
    log "Deploying infrastructure components..."
    
    # Create namespace
    info "Creating namespace..."
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/namespace.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/k8s/manifests/namespace.yaml"
    fi
    
    # Deploy secrets (placeholder - should use external secret management in production)
    info "Deploying secrets..."
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/secrets.yaml"
    else
        # In production, this should be handled by external secret management
        warn "Using placeholder secrets. Configure external secret management for production!"
        kubectl apply -f "$PROJECT_ROOT/k8s/manifests/secrets.yaml"
    fi
    
    # Deploy ConfigMaps
    info "Deploying configuration..."
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/configmap.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/k8s/manifests/configmap.yaml"
    fi
    
    # Deploy databases
    info "Deploying databases..."
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/qdrant.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/k8s/manifests/qdrant.yaml"
        
        # Wait for databases to be ready
        kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=qdrant -n "$NAMESPACE" --timeout=300s || warn "Qdrant may not be ready"
    fi
    
    log "Infrastructure deployment completed"
}

# Deploy application
deploy_application() {
    log "Deploying application..."
    
    # Update image tag in deployment
    local temp_manifest="/tmp/qdrant-neo4j-crawl4ai-mcp-${TIMESTAMP}.yaml"
    sed "s|image: ghcr.io/your-username/qdrant-neo4j-crawl4ai-mcp:latest|image: $REGISTRY/qdrant-neo4j-crawl4ai-mcp:$IMAGE_TAG|g" \
        "$PROJECT_ROOT/k8s/manifests/qdrant-neo4j-crawl4ai-mcp.yaml" > "$temp_manifest"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$temp_manifest"
    else
        kubectl apply -f "$temp_manifest"
        
        # Wait for deployment rollout
        kubectl rollout status deployment/qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE" --timeout=600s
        
        # Verify deployment health
        kubectl wait --for=condition=available deployment/qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE" --timeout=300s
    fi
    
    # Deploy ingress
    info "Deploying ingress..."
    if [[ "$DRY_RUN" == "true" ]]; then
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/k8s/manifests/ingress.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/k8s/manifests/ingress.yaml"
    fi
    
    # Cleanup temporary files
    rm -f "$temp_manifest"
    
    log "Application deployment completed"
}

# Deploy monitoring stack
deploy_monitoring() {
    if [[ "$ENABLE_MONITORING" != "true" ]]; then
        warn "Skipping monitoring stack deployment"
        return 0
    fi
    
    log "Deploying monitoring stack..."
    
    # Deploy with Docker Compose in development
    if [[ "$ENVIRONMENT" == "development" ]]; then
        info "Starting monitoring stack with Docker Compose..."
        if [[ "$DRY_RUN" == "true" ]]; then
            info "Would run: docker-compose -f $PROJECT_ROOT/docker-compose.yml up -d prometheus grafana loki promtail jaeger"
        else
            cd "$PROJECT_ROOT"
            docker-compose up -d prometheus grafana loki promtail jaeger
        fi
    else
        # In production, monitoring would be deployed via Helm charts or separate manifests
        warn "Monitoring stack deployment for production should be configured separately"
    fi
    
    log "Monitoring stack deployment completed"
}

# Post-deployment validation
post_deployment_validation() {
    log "Running post-deployment validation..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        info "Skipping validation in dry-run mode"
        return 0
    fi
    
    # Check pod status
    info "Checking pod status..."
    kubectl get pods -n "$NAMESPACE" -o wide
    
    # Check service endpoints
    info "Checking service endpoints..."
    kubectl get endpoints -n "$NAMESPACE"
    
    # Health check
    info "Performing health check..."
    local health_check_retries=0
    local max_retries=30
    
    while [[ $health_check_retries -lt $max_retries ]]; do
        if kubectl exec -n "$NAMESPACE" deployment/qdrant-neo4j-crawl4ai-mcp -- curl -f -s http://localhost:8000/health &> /dev/null; then
            log "Health check passed"
            break
        else
            ((health_check_retries++))
            info "Health check attempt $health_check_retries/$max_retries failed, retrying in 10 seconds..."
            sleep 10
        fi
    done
    
    if [[ $health_check_retries -eq $max_retries ]]; then
        error "Health check failed after $max_retries attempts"
    fi
    
    # Check metrics endpoint
    info "Checking metrics endpoint..."
    if kubectl exec -n "$NAMESPACE" deployment/qdrant-neo4j-crawl4ai-mcp -- curl -f -s http://localhost:9090/metrics &> /dev/null; then
        log "Metrics endpoint is accessible"
    else
        warn "Metrics endpoint is not accessible"
    fi
    
    log "Post-deployment validation completed successfully"
}

# Send notification
send_notification() {
    local status="$1"
    local message="$2"
    
    if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
        local color="good"
        if [[ "$status" == "error" ]]; then
            color="danger"
        elif [[ "$status" == "warning" ]]; then
            color="warning"
        fi
        
        local payload=$(cat << EOF
{
    "attachments": [
        {
            "color": "$color",
            "title": "Qdrant Neo4j Crawl4AI MCP Server Deployment",
            "fields": [
                {
                    "title": "Environment",
                    "value": "$ENVIRONMENT",
                    "short": true
                },
                {
                    "title": "Image Tag",
                    "value": "$IMAGE_TAG",
                    "short": true
                },
                {
                    "title": "Status",
                    "value": "$status",
                    "short": true
                },
                {
                    "title": "Timestamp",
                    "value": "$(date)",
                    "short": true
                }
            ],
            "text": "$message"
        }
    ]
}
EOF
        )
        
        curl -X POST -H 'Content-type: application/json' --data "$payload" "$SLACK_WEBHOOK_URL" &> /dev/null || warn "Failed to send Slack notification"
    fi
}

# Rollback deployment
rollback_deployment() {
    error_msg="$1"
    
    warn "Deployment failed: $error_msg"
    warn "Initiating rollback..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would rollback deployment"
        return 0
    fi
    
    # Rollback application deployment
    if kubectl rollout history deployment/qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE" &> /dev/null; then
        kubectl rollout undo deployment/qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE"
        kubectl rollout status deployment/qdrant-neo4j-crawl4ai-mcp -n "$NAMESPACE" --timeout=300s
        warn "Application deployment rolled back"
    fi
    
    send_notification "error" "Deployment failed and was rolled back: $error_msg"
    error "Deployment failed: $error_msg"
}

# Cleanup function
cleanup() {
    info "Cleaning up temporary files..."
    rm -f /tmp/qdrant-neo4j-crawl4ai-mcp-*.yaml
    rm -f /tmp/qdrant-neo4j-crawl4ai-mcp-backup_*.tar.gz
}

# Trap cleanup on exit
trap cleanup EXIT

# Main deployment function
main() {
    log "Starting Qdrant Neo4j Crawl4AI MCP Server deployment"
    log "Environment: $ENVIRONMENT"
    log "Namespace: $NAMESPACE"
    log "Image: $REGISTRY/qdrant-neo4j-crawl4ai-mcp:$IMAGE_TAG"
    log "Dry run: $DRY_RUN"
    
    # Set error handler for rollback
    set -e
    trap 'rollback_deployment "Unexpected error occurred"' ERR
    
    validate_environment
    pre_deployment_checks
    run_tests
    backup_deployment
    deploy_infrastructure
    deploy_application
    deploy_monitoring
    post_deployment_validation
    
    # Remove error trap after successful deployment
    trap - ERR
    
    log "Deployment completed successfully!"
    
    # Display access information
    if [[ "$DRY_RUN" != "true" ]]; then
        echo
        log "Access Information:"
        info "API Endpoint: https://api.qdrant-neo4j-crawl4ai-mcp.company.com"
        info "Health Check: https://api.qdrant-neo4j-crawl4ai-mcp.company.com/health"
        info "Metrics: https://api.qdrant-neo4j-crawl4ai-mcp.company.com/metrics"
        if [[ "$ENABLE_MONITORING" == "true" && "$ENVIRONMENT" == "development" ]]; then
            info "Grafana: http://localhost:3000 (admin/admin)"
            info "Prometheus: http://localhost:9090"
        fi
        echo
        log "Deployment logs: $LOG_FILE"
    fi
    
    send_notification "success" "Deployment completed successfully for environment: $ENVIRONMENT"
}

# Parse arguments and run main function
parse_args "$@"
main