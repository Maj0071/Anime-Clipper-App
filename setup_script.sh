#!/bin/bash

echo "======================================"
echo "Anime Auto-Clipper - Setup Script"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi
print_status "Docker is installed"

if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi
print_status "Docker Compose is installed"

echo ""

# Create necessary directories
echo "Creating directory structure..."
mkdir -p backend/app/api
mkdir -p backend/app/services
mkdir -p backend/app/workers
mkdir -p backend/alembic/versions
mkdir -p backend/tests
mkdir -p backend/logs
mkdir -p frontend/src/app/analyze/[id]
mkdir -p frontend/src/app/gallery/[id]
mkdir -p frontend/src/app/export/[id]
mkdir -p frontend/src/components
mkdir -p frontend/src/lib
mkdir -p frontend/public
mkdir -p docker
print_status "Directories created"

echo ""

# Create environment files if they don't exist
echo "Setting up environment files..."

if [ ! -f backend/.env ]; then
    cat > backend/.env << EOF
DATABASE_URL=postgresql://clipper:clipper_dev_password@db:5432/anime_clipper
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=anime-clips
JWT_SECRET=dev_jwt_secret_change_in_production
EOF
    print_status "Created backend/.env"
else
    print_warning "backend/.env already exists, skipping"
fi

if [ ! -f frontend/.env.local ]; then
    cat > frontend/.env.local << EOF
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
    print_status "Created frontend/.env.local"
else
    print_warning "frontend/.env.local already exists, skipping"
fi

echo ""

# Start Docker containers
echo "Starting Docker containers..."
docker-compose up -d

echo ""
echo "Waiting for services to be ready..."
sleep 10

# Check if services are running
if docker-compose ps | grep -q "Up"; then
    print_status "Docker services are running"
else
    print_error "Failed to start Docker services"
    exit 1
fi

echo ""

# Run database migrations
echo "Running database migrations..."
docker-compose exec -T api alembic upgrade head
if [ $? -eq 0 ]; then
    print_status "Database migrations completed"
else
    print_error "Database migrations failed"
    exit 1
fi

echo ""

# Create MinIO bucket
echo "Setting up S3 bucket in MinIO..."
docker-compose exec -T minio mc alias set myminio http://localhost:9000 minioadmin minioadmin
docker-compose exec -T minio mc mb myminio/anime-clips --ignore-existing
if [ $? -eq 0 ]; then
    print_status "S3 bucket created"
else
    print_warning "Bucket might already exist"
fi

echo ""

# Install frontend dependencies (if running locally)
if [ -f frontend/package.json ]; then
    echo "Installing frontend dependencies..."
    cd frontend
    if command -v npm &> /dev/null; then
        npm install
        print_status "Frontend dependencies installed"
    else
        print_warning "npm not found, skipping local frontend setup"
    fi
    cd ..
fi

echo ""
echo "======================================"
echo "Setup Complete! 🎉"
echo "======================================"
echo ""
echo "Services are now running:"
echo ""
echo "  Frontend:        http://localhost:3000"
echo "  API:             http://localhost:8000"
echo "  API Docs:        http://localhost:8000/docs"
echo "  MinIO Console:   http://localhost:9001"
echo "  Celery Flower:   http://localhost:5555"
echo ""
echo "Credentials:"
echo "  MinIO:   minioadmin / minioadmin"
echo ""
echo "To stop all services:"
echo "  docker-compose down"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To restart a service:"
echo "  docker-compose restart [service-name]"
echo ""
echo "Happy clipping! ✂️🎬"
echo ""