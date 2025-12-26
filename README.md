🤖 LLM Quiz Solver
An automated system that uses AI to solve quiz questions by analyzing data from files, web pages, and APIs.

✨ Features
AI-Powered: Uses Groq or Gemini LLMs to understand and solve questions

Multi-Format Support: Processes CSV, PDF, Excel, JSON, HTML, and images

Web Scraping: Built-in browser for JavaScript-rendered content

Auto-Submission: Automatically submits answers with retry logic

Rate Limiting: Smart API rate limit handling

🚀 Quick Start
Install Dependencies

bash
pip install -r requirements.txt
playwright install chromium
Configure API Keys (.env file)

env
GROQ_API_KEY=your_groq_key_here      # OR GEMINI_API_KEY
SECRET=your_secret_here
EMAIL=your_email@example.com
Run the Server

bash
python main.py
📋 API Usage
python
import requests

payload = {
    "email": "your_email@example.com",
    "secret": "your_secret",
    "url": "https://quiz-platform.com/quiz-1"
}

response = requests.post("http://localhost:8000/quiz", json=payload)
🛠️ Project Structure
main.py - FastAPI server entry point

quiz_solver.py - Main quiz solving logic

llm_client.py - Multi-LLM client (Groq + Gemini)

data_processor.py - File processing and data analysis

config.py - Configuration management

📊 Supported Tasks
✅ Data analysis (CSV/Excel calculations)

✅ Web scraping and pattern extraction

✅ PDF text extraction

✅ Command generation (uv, git)

✅ Direct Q&A and math problems

⚡ Performance Tips
Groq API is faster and has better rate limits

System includes 3-minute timeout per quiz

Automatic retry on failed submissions

Caching for repeated data fetches
