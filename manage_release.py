import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Configuration
RELEASES_DIR = "releases"
BACKEND_IMAGE = "memex-backend:latest"
DB_IMAGE = "docker.m.daocloud.io/pgvector/pgvector:pg16" # Match docker-compose.prod.yml
# Note: For DB, we might want to pull it first if not present, but user said "Offline", 
# so we assume it exists or we pull it once.
# The user prompt for Task 1, Menu [2] says: "memex-backend + pgvector/pgvector:pg16"
# I will use the tag specified in the user requirement.

def ensure_releases_dir():
    if not os.path.exists(RELEASES_DIR):
        os.makedirs(RELEASES_DIR)
        print(f"Created releases directory: {RELEASES_DIR}")

def run_command(command, shell=True):
    print(f"Executing: {command}")
    try:
        subprocess.check_call(command, shell=shell)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return False

def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M")

def quick_update():
    """Menu [1] Quick Update: Build & Save Backend Only"""
    print("\n=== [1] Quick Update (Backend Only) ===")
    timestamp = get_timestamp()
    
    # 1. Build
    print("Step 1/2: Building Backend Image...")
    # Using specific tagging to avoid cache issues
    if not run_command(f"docker build -t {BACKEND_IMAGE} ."):
        return
    
    # 2. Save
    print("Step 2/2: Saving to .tar...")
    filename = f"memex_backend_{timestamp}.tar"
    filepath = os.path.join(RELEASES_DIR, filename)
    
    if run_command(f"docker save -o {filepath} {BACKEND_IMAGE}"):
        print(f"\nSUCCESS! Release saved to: {filepath}")
        print(f"Transfer this file to NAS and run: docker load -i {filename}")

def full_deployment():
    """Menu [2] Full Deployment: Backend + DB"""
    print("\n=== [2] Full Deployment (Backend + DB) ===")
    timestamp = get_timestamp()
    
    # 1. Build Backend
    print("Step 1/3: Building Backend Image...")
    if not run_command(f"docker build -t {BACKEND_IMAGE} ."):
        return

    # 2. Pull DB (Optional, just to be safe make sure we have it)
    print("Step 2/3: Checking DB Image...")
    # We don't force pull because of network restrictions, we assume it might exist.
    # But if we are exporting it, we need it locally.
    # The requirement says: "NAS network restricted... build local -> offline transfer".
    # So we assume PC network is fine.
    print(f"Ensure you have {DB_IMAGE} locally.")
    
    # 3. Save Both
    print("Step 3/3: Saving All Images to .tar...")
    filename = f"memex_full_{timestamp}.tar"
    filepath = os.path.join(RELEASES_DIR, filename)
    
    images = f"{BACKEND_IMAGE} {DB_IMAGE}"
    if run_command(f"docker save -o {filepath} {images}"):
        print(f"\nSUCCESS! Full release saved to: {filepath}")
        print(f"Transfer this file to NAS and run: docker load -i {filename}")

def cleanup_releases():
    """Menu [3] Cleanup Old Releases"""
    print("\n=== [3] Cleanup Releases ===")
    files = [f for f in os.listdir(RELEASES_DIR) if f.endswith(".tar")]
    if not files:
        print("No .tar files found in releases/.")
        return

    print(f"Found {len(files)} files:")
    for f in files:
        file_path = os.path.join(RELEASES_DIR, f)
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f" - {f} ({size_mb:.2f} MB)")
    
    confirm = input("Are you sure you want to delete ALL these files? (y/n): ").lower()
    if confirm == 'y':
        for f in files:
            os.remove(os.path.join(RELEASES_DIR, f))
            print(f"Deleted: {f}")
        print("Cleanup complete.")
    else:
        print("Operation cancelled.")

def main_menu():
    ensure_releases_dir()
    while True:
        print("\n==========================================")
        print("   Memex Offline Release Manager (NAS)")
        print("==========================================")
        print("[1] Quick Update (Backend Code Only)")
        print("[2] Full Deployment (Backend + DB)")
        print("[3] Cleanup releases/ folder")
        print("[4] Force Rebuild (No Cache) [Use if frontend Missing]")
        print("[0] Exit")
        
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            quick_update()
        elif choice == '2':
            full_deployment()
        elif choice == '3':
            cleanup_releases()
        elif choice == '4':
            print("\n=== [4] Force Rebuild (No Cache) ===")
            timestamp = get_timestamp()
            # 1. Build No Cache
            print("Step 1/2: Force Building Backend Image...")
            if not run_command(f"docker build --no-cache -t {BACKEND_IMAGE} ."):
                continue # Back to menu
            
            # 2. Save
            print("Step 2/2: Saving to .tar...")
            filename = f"memex_backend_force_{timestamp}.tar"
            filepath = os.path.join(RELEASES_DIR, filename)
            
            if run_command(f"docker save -o {filepath} {BACKEND_IMAGE}"):
                print(f"\nSUCCESS! Release saved to: {filepath}")
        elif choice == '0':
            print("Exiting...")
            sys.exit(0)
        else:
            print("Invalid option, please try again.")

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)
