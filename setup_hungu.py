import os

# Define the project structure and complete source code for each service
# Files will now be created in the current directory (no 'hungu/' prefix)
project_structure = {
    # 1. ROOT CONFIGURATION
    "README.md": """# HUNGU: AI-Powered Actionable News & Gazette Intelligence
HUNGU is a microservices-based news platform prioritizing hyper-local intelligence (Suburb -> Country) with AI-generated scriptural insights.

## Quick Start
1. Edit `.env` with your API keys.
2. Run `make up` to start all services.
3. Access the web app at `http://localhost:3000`.
""",
    
    "GUIDE.md": """# HUNGU: Development Guide
Refer to this for Copilot prompts.
- **Web**: React-based mobile-first UI.
- **API**: FastAPI handling prioritization logic.
- **Worker**: Scraper and Gemini AI integration.
""",

    "Makefile": """up:
	docker-compose up -d --build
down:
	docker-compose down
logs:
	docker-compose logs -f
""",

    "docker-compose.yml": """version: '3.8'
services:
  web:
    build: ./services/web
    ports: ["3000:80"]
    networks: ["hungu-net"]
  api:
    build: ./services/api
    ports: ["8000:8000"]
    env_file: .env
    networks: ["hungu-net"]
  worker:
    build: ./services/worker
    env_file: .env
    networks: ["hungu-net"]

networks:
  hungu-net:
    driver: bridge
""",

    ".env.example": """GEMINI_API_KEY=your_key_here
DB_URL=postgresql://hungu:pass@db/hungu
FIREBASE_CONFIG={}
""",

    # 2. API SERVICE (FastAPI)
    "services/api/main.py": """from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="HUNGU API")

class Article(BaseModel):
    id: int
    title: str
    location_tier: str # Suburb, City, Province, Country
    category: str
    impact: str
    verse: str

@app.get("/feed")
async def get_feed(suburb: str, city: str):
    # Mock Prioritization Logic: Suburb -> City -> Province -> Country
    # In production, this queries PostgreSQL
    return {"message": f"Feed for {suburb}, {city} sorted by priority."}
""",
    "services/api/Dockerfile": "FROM python:3.10-slim\nRUN pip install fastapi uvicorn\nCOPY . /app\nWORKDIR /app\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",

    # 3. WORKER SERVICE (Scraper & AI)
    "services/worker/main.py": """import os
import time
import requests

GEMINI_KEY = os.getenv("GEMINI_API_KEY")

def process_with_ai(text):
    # Logic to call Gemini 2.5 Flash
    # Generate: 1. Summary, 2. Local Impact, 3. Bible Verse
    print("Processing news with Gemini...")
    return "AI Processed Content"

def scrape_gazette():
    print("Checking gov.za for new gazettes...")
    # Scraper logic here
    pass

if __name__ == "__main__":
    while True:
        scrape_gazette()
        time.sleep(3600) # Check every hour
""",
    "services/worker/Dockerfile": "FROM python:3.10-slim\nRUN pip install requests beautifulsoup4 playwright\nCOPY . /app\nWORKDIR /app\nCMD [\"python\", \"main.py\"]",

    # 4. WEB SERVICE (Frontend)
    "services/web/index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HUNGU | News</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50">
    <div id="app" class="max-w-md mx-auto min-h-screen bg-white shadow-xl">
        <header class="p-4 border-b flex justify-between items-center sticky top-0 bg-white/80 backdrop-blur">
            <h1 class="text-2xl font-black italic">HUNGU</h1>
            <div class="w-8 h-8 bg-black rounded-full"></div>
        </header>
        <main class="p-4">
            <div class="bg-black text-white p-6 rounded-[2rem] mb-6">
                <p class="text-xs font-bold text-blue-400 uppercase mb-1">Daily Pulse</p>
                <h2 class="text-xl font-bold">Good Morning, User</h2>
                <button class="mt-4 w-full bg-white text-black py-3 rounded-xl font-bold text-sm">Read News For Me</button>
            </div>
            <!-- Feed will be injected here -->
            <div id="feed" class="space-y-8"></div>
        </main>
    </div>
</body>
</html>""",
    "services/web/Dockerfile": "FROM nginx:alpine\nCOPY index.html /usr/share/nginx/html/index.html",
}

def create_project():
    for path, content in project_structure.items():
        # Get the directory name from the path
        dir_name = os.path.dirname(path)
        # Create directories if they exist in the path string and don't exist yet
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        
        # Write the file directly to the path
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    
    print("🚀 HUNGU Project Structure created in the current directory!")
    print("👉 Next: Run 'make up' to start the services.")

if __name__ == "__main__":
    create_project()