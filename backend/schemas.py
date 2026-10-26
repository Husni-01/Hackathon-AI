from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class TestCase(BaseModel):
    input: str
    expected_output: str

class ExecutionRequest(BaseModel):
    problem_description: str = Field(..., description="The hackathon problem text")
    language: Literal["python", "cpp"] = Field(default="python")
    max_iterations: int = Field(default=20, description="Max MCTS sandbox loops")
    time_limit_seconds: int = Field(default=5, description="Execution timeout per test")
    test_cases: List[TestCase] = Field(..., description="List of test cases to run")

class StreamEvent(BaseModel):
    event_type: Literal["status", "sandbox_result", "final_solution", "error"]
    message: str
    iteration: Optional[int] = None
    code_snippet: Optional[str] = None
    passed: Optional[bool] = None
