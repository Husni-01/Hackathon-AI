import logging
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from schemas import ExecutionRequest
from mcts import run_mcts

logging.basicConfig(
    filename='mcts_execution.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcts")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/solve")
async def solve(req: ExecutionRequest):
    logger.info(f"Received solve request for {req.language} with {len(req.test_cases)} test cases.")
    return StreamingResponse(
        run_mcts(req.problem_description, req.language, req.max_iterations, req.time_limit_seconds, req.test_cases), 
        media_type="text/event-stream"
    )
