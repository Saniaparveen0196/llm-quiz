from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import asyncio
import uvicorn
from datetime import datetime, timedelta
from config import Config
from quiz_solver import QuizSolver
import json

# Store active quiz sessions
active_sessions: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    try:
        Config.validate()
        print("🚀 Server starting...")
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        raise
    yield
    # Shutdown - close all active browser sessions
    print("🛑 Shutting down - cleaning up resources...")
    for session_id, session in list(active_sessions.items()):
        try:
            solver = session.get("solver")
            if solver:
                await solver.close_browser()
        except Exception as e:
            print(f"⚠ Error closing browser for session {session_id}: {e}")
    active_sessions.clear()

app = FastAPI(title="Groq Quiz Solver API", lifespan=lifespan)

class QuizRequest(BaseModel):
    email: str
    secret: str
    url: str
    # Allow additional fields
    class Config:
        extra = "allow"

class QuizResponse(BaseModel):
    status: str
    message: str

@app.post("/quiz")
async def handle_quiz(request: Request):
    """Handle quiz task POST request"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Validate request
    try:
        quiz_request = QuizRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}")
    
    # Verify secret
    if quiz_request.secret != Config.SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    # Verify email
    if quiz_request.email != Config.EMAIL:
        raise HTTPException(status_code=403, detail="Invalid email")
    
    # Initialize quiz solver with Groq API key
    solver = QuizSolver(Config.GROQ_API_KEY)
    
    # Start solving quiz asynchronously
    session_id = f"{quiz_request.email}_{datetime.now().timestamp()}"
    start_time = datetime.now()
    
    # Store session
    active_sessions[session_id] = {
        "start_time": start_time,
        "url": quiz_request.url,
        "solver": solver,
        "email": quiz_request.email,
        "secret": quiz_request.secret
    }
    
    # Process quiz in background
    asyncio.create_task(process_quiz(session_id, quiz_request.url, quiz_request.email, quiz_request.secret))
    
    # Return immediate response
    return JSONResponse(status_code=200, content={
        "status": "accepted",
        "message": "Quiz task received and processing started"
    })

async def process_quiz(session_id: str, quiz_url: str, email: str, secret: str):
    """Process quiz asynchronously"""
    session = active_sessions.get(session_id)
    if not session:
        return
    
    solver = session["solver"]
    start_time = session["start_time"]
    timeout = timedelta(seconds=Config.QUIZ_TIMEOUT)
    
    try:
        current_url = quiz_url
        
        while current_url and (datetime.now() - start_time) < timeout:
            print(f"\n{'='*60}")
            print(f"📝 Processing quiz URL: {current_url}")
            
            # Fetch quiz page
            try:
                quiz_data = await solver.fetch_quiz_page(current_url)
            except Exception as e:
                print(f"❌ Error fetching quiz page {current_url}: {str(e)}")
                break
            
            if not quiz_data.get("question"):
                print(f"⚠ No question found on page {current_url}")
                break
            
            # Get submit URL
            submit_url = quiz_data.get("submit_url")
            if not submit_url:
                import re
                from urllib.parse import urljoin
                url_match = re.search(r'https?://[^\s<>"\'`]+/submit[^\s<>"\'`]*', quiz_data.get("question", ""))
                if url_match:
                    submit_url = url_match.group()
                else:
                    rel_match = re.search(r'["\']?/submit[^\s<>"\'`]*["\']?', quiz_data.get("question", ""))
                    if rel_match:
                        rel_url = rel_match.group().strip('"\'')
                        submit_url = urljoin(current_url, rel_url)
            
            if not submit_url:
                print(f"⚠ No submit URL found for {current_url}")
                if '/project2' in current_url:
                    from urllib.parse import urlparse
                    parsed = urlparse(current_url)
                    submit_url = f"{parsed.scheme}://{parsed.netloc}/submit"
                    print(f"📌 Using fixed submit URL for /project2*: {submit_url}")
                else:
                    break
            
            if submit_url and not submit_url.startswith('http'):
                from urllib.parse import urljoin
                submit_url = urljoin(current_url, submit_url)
            
            print(f"📤 Submit URL: {submit_url}")
            print(f"📝 Question preview: {quiz_data.get('question', '')[:200]}...")
            
            # Solve quiz
            solution = await solver.solve_quiz(quiz_data)
            answer = solution["answer"]
            
            if answer is None:
                print(f"❌ Could not determine answer for {current_url}")
                print(f"💭 Solution details: {solution.get('reasoning', '')[:500]}")
                break
            
            print(f"✅ Answer: {answer}")
            
            # Submit answer with retry logic
            retry_count = 0
            question_solved = False
            max_retries_safety = 50
            
            while retry_count < max_retries_safety and (datetime.now() - start_time) < timeout and not question_solved:
                result = solver.submit_answer(submit_url, email, secret, current_url, answer)
                
                if result.get("correct"):
                    print(f"🎉 Correct answer submitted for {current_url}")
                    question_solved = True
                    next_url = result.get("url")
                    if next_url:
                        print(f"➡️ Next URL received: {next_url}")
                        current_url = next_url
                        break
                    else:
                        print("🏆 Quiz completed! No more URLs.")
                        return
                else:
                    retry_count += 1
                    reason = result.get("reason", "")
                    print(f"❌ Attempt {retry_count} failed: {reason}")
                    
                    next_url = result.get("url")
                    if next_url and next_url != current_url:
                        print(f"⏩ Received new URL to skip to: {next_url}")
                        current_url = next_url
                        break
                    
                    if (datetime.now() - start_time) >= timeout:
                        print(f"⏰ Timeout reached (3 minutes) for {current_url}")
                        return
                    
                    if reason:
                        quiz_data["question"] += f"\nPrevious attempt feedback: {reason}"
                    print("🔄 Retrying with feedback...")
                    solution = await solver.solve_quiz(quiz_data)
                    answer = solution["answer"]
                    
                    if answer is None:
                        print(f"❌ Could not determine answer after retry. Stopping for {current_url}")
                        return
    
    except Exception as e:
        import traceback
        print(f"❌ Error processing quiz: {str(e)}")
        print(traceback.format_exc())
    finally:
        await solver.close_browser()
        if session_id in active_sessions:
            del active_sessions[session_id]

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Groq Quiz Solver API",
        "endpoints": {
            "POST /quiz": "Submit quiz task",
            "GET /health": "Health check"
        }
    }

if __name__ == "__main__":
    try:
        Config.validate()
        uvicorn.run(app, host=Config.HOST, port=Config.PORT)
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("Please set the following environment variables:")
        print("- GROQ_API_KEY (get from https://console.groq.com)")
        print("- SECRET")
        print("- EMAIL")