import os
import subprocess
import sys

# Install packages
def install_packages():
    print("Installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    # Install Playwright browsers
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

# Create folders for memory & DB
def create_folders():
    if not os.path.exists("chroma_memory"):
        os.makedirs("chroma_memory")
        print("Created folder: chroma_memory")
    if not os.path.exists("brain.db"):
        open("brain.db", "a").close()
        print("Created SQLite database: brain.db")

if __name__ == "__main__":
    install_packages()
    create_folders()
    print("Setup complete!")
