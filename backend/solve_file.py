"""
CLI tool to run Hackathon AI directly from a Markdown file (e.g. Implementation plan.md)

Usage:
    python solve_file.py "Implementation plan.md"
    python solve_file.py "Implementation plan.md" --language cpp --max-iter 20
"""

import sys
import os
import argparse
import json
import re
import httpx

def parse_markdown_file(file_path: str):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Attempt to extract test cases if defined in markdown codeblocks or tables
    test_cases = []
    # Pattern: Input:\n```...\n```\nOutput:\n```...\n```
    tc_pattern = re.findall(
        r"(?:Input|Sample Input)[:\s]*\n```(?:[a-zA-Z]*)\n(.*?)\n```[\s\S]*?(?:Output|Sample Output|Expected Output)[:\s]*\n```(?:[a-zA-Z]*)\n(.*?)\n```",
        content,
        re.IGNORECASE
    )
    for inp, out in tc_pattern:
        test_cases.append({"input": inp.strip(), "expected_output": out.strip()})
        
    return content.strip(), test_cases

def main():
    parser = argparse.ArgumentParser(description="Hackathon AI File-Based Solver")
    parser.add_argument("file", help="Path to markdown or text file (e.g. Implementation plan.md)")
    parser.add_argument("--language", choices=["python", "cpp"], default="python", help="Programming language (default: python)")
    parser.add_argument("--max-iter", type=int, default=20, help="Max MCTS iterations (default: 20)")
    parser.add_argument("--timeout", type=int, default=5, help="Test timeout in seconds (default: 5)")
    parser.add_argument("--url", default="http://localhost:8000/api/v1/solve", help="Backend SSE URL")
    
    args = parser.parse_args()
    
    try:
        problem_text, extracted_tc = parse_markdown_file(args.file)
    except Exception as e:
        print(f"[Error] {e}")
        sys.exit(1)
        
    if not extracted_tc:
        print("[Notice] No sample test cases auto-detected in the markdown. Adding a dummy test case.")
        extracted_tc = [{"input": "", "expected_output": ""}]
    else:
        print(f"[Info] Auto-detected {len(extracted_tc)} sample test case(s) from {args.file}")
        
    payload = {
        "problem_description": problem_text,
        "language": args.language,
        "max_iterations": args.max_iter,
        "time_limit_seconds": args.timeout,
        "test_cases": extracted_tc
    }
    
    print(f"\n==========================================")
    print(f"🚀 Submitting '{args.file}' to Hackathon AI ({args.language.upper()})")
    print(f"==========================================\n")
    
    try:
        with httpx.Client(timeout=300.0) as client:
            with client.stream("POST", args.url, json=payload) as response:
                if response.status_code != 200:
                    print(f"[Error] Backend returned status code {response.status_code}")
                    return
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        ev_type = data.get("event_type", "").upper()
                        msg = data.get("message", "")
                        iter_num = data.get("iteration")
                        iter_str = f" [Iter {iter_num}]" if iter_num else ""
                        print(f"[{ev_type}{iter_str}] {msg}")
                        
                        if data.get("code_snippet"):
                            print("\n--- Generated Code ---")
                            print(data["code_snippet"])
                            print("----------------------\n")
                            
                        if ev_type == "FINAL_SOLUTION":
                            print("\n🎉 SUCCESS: Optimal solution discovered and verified!")
                            break
    except Exception as e:
        print(f"[Error connecting to backend] {e}")
        print("Ensure the backend server is running: python -m uvicorn main:app --reload --port 8000")

if __name__ == "__main__":
    main()
