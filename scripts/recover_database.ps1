# PostgreSQL Database Recovery Script (PowerShell)
# Fix WAL corruption issues

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Checking database status..." -ForegroundColor Cyan

# Stop container
Write-Host "Stopping database container..." -ForegroundColor Yellow
docker-compose stop db

# Backup current data directory
$backupDir = "./data/postgres_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
if (Test-Path "./data/postgres") {
    Write-Host "Backing up current database directory to: $backupDir" -ForegroundColor Yellow
    Copy-Item -Path "./data/postgres" -Destination $backupDir -Recurse -Force
}

Write-Host ""
Write-Host "Please select recovery option:" -ForegroundColor Cyan
Write-Host "1. Try to fix WAL (may recover some data)" -ForegroundColor Green
Write-Host "2. Reinitialize database (will lose all data)" -ForegroundColor Red
$choice = Read-Host "Enter option (1/2)"

switch ($choice) {
    "1" {
        Write-Host "Attempting to fix WAL..." -ForegroundColor Yellow
        
        # Use pg_resetwal to reset WAL
        docker run --rm `
            -v "${PWD}/data/postgres:/var/lib/postgresql/data" `
            pgvector/pgvector:pg16 `
            bash -c "pg_resetwal -f /var/lib/postgresql/data"
        
        Write-Host "WAL reset complete, starting database..." -ForegroundColor Green
        docker-compose up -d db
        
        Write-Host "Waiting for database to start..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        
        # Check database status
        $ready = docker exec memex-db pg_isready -U memex 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Database started successfully!" -ForegroundColor Green
            Write-Host "Please check data integrity and backup immediately!" -ForegroundColor Yellow
        } else {
            Write-Host "Database startup failed, may need to reinitialize" -ForegroundColor Red
            Write-Host "Please run option 2 to reinitialize database" -ForegroundColor Yellow
        }
    }
    "2" {
        Write-Host "WARNING: This will delete all database data!" -ForegroundColor Red
        $confirm = Read-Host "Confirm reinitialize? (yes/no)"
        if ($confirm -eq "yes") {
            Write-Host "Deleting corrupted database directory..." -ForegroundColor Yellow
            Remove-Item -Path "./data/postgres/*" -Recurse -Force -ErrorAction SilentlyContinue
            Get-ChildItem -Path "./data/postgres" -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
            
            Write-Host "Reinitializing database..." -ForegroundColor Yellow
            docker-compose up -d db
            
            Write-Host "Waiting for database initialization..." -ForegroundColor Yellow
            Start-Sleep -Seconds 10
            
            Write-Host "Database reinitialized!" -ForegroundColor Green
            Write-Host "Please reconfigure models and settings" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Next step: Run 'python scripts/init_database.py' to create tables" -ForegroundColor Yellow
        } else {
            Write-Host "Operation cancelled" -ForegroundColor Yellow
        }
    }
    default {
        Write-Host "Invalid option" -ForegroundColor Red
        exit 1
    }
}

