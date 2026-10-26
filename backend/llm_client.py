import httpx
import re

async def _call_ollama(prompt: str) -> str:
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": prompt,
        "stream": False
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()

from utils.parser import estimate_required_complexity

async def generate_blueprints(problem: str) -> list[str]:
    complexity_string = estimate_required_complexity(problem)
    system_prompt = (
        "Act as a Senior Algorithm Architect. Output exactly 3 completely different, "
        "high-level algorithmic approaches to solve the problem (e.g., DP vs. Graph vs. Greedy). "
        "Do not write code. "
        f"You must restrict your 3 algorithmic blueprints to algorithms that satisfy the required time complexity constraint: {complexity_string} "
        "Separate each approach with the exact delimiter '||BLUEPRINT||'."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}"
    response = await _call_ollama(full_prompt)
    
    if "||BLUEPRINT||" in response:
        blueprints = [b.strip() for b in response.split("||BLUEPRINT||") if b.strip()]
    else:
        splits = re.split(r'(?:\n|\A)(?:Approach\s+\d+|Option\s+\d+|\d+\.)[:\.\s]', response, flags=re.IGNORECASE)
        blueprints = [s.strip() for s in splits if s.strip()]
        
    if not blueprints:
        blueprints = [response.strip()]
    return blueprints[:3]

async def generate_code_from_blueprint(problem: str, blueprint: str, language: str) -> str:
    template_instruction = ""
    if language == "cpp":
        template_instruction = (
            "\nWrap your logic inside this exact competitive programming template:\n"
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "typedef long long ll;\n"
            "int main() {\n"
            "    ios::sync_with_stdio(0); cin.tie(0);\n"
            "    // Logic here\n"
            "    return 0;\n"
            "}"
        )
    system_prompt = (
        f"Act as an expert Coder. Given the problem and this specific mathematical blueprint, "
        f"write the highly optimized implementation in {language}. Output ONLY raw code. "
        f"Do NOT wrap code in markdown backticks. Do NOT provide explanations.{template_instruction}"
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}\n\nBlueprint:\n{blueprint}"
    return await _call_ollama(full_prompt)

async def generate_reflection(problem: str, failed_code: str, sandbox_error: str) -> str:
    system_prompt = (
        "Act as a strict Code Critic. The Coder's implementation failed the sandbox tests. "
        "Analyze the `failed_code` and the `sandbox_error`. Explain the logical flaw and dictate "
        "exactly how the Coder must rewrite the algorithm in the next iteration."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}\n\nFailed Code:\n{failed_code}\n\nSandbox Error:\n{sandbox_error}"
    return await _call_ollama(full_prompt)

from utils.parser import extract_clean_code

async def generate_adversarial_harness(problem: str) -> str:
    system_prompt = (
        "Act as a Ruthless Competitive Programming Judge and Hack Generator.\n"
        "Given the problem description, write a standalone Python 3 script that outputs a JSON object to stdout with the following exact structure:\n"
        "{\n"
        '  "edge_cases": [\n'
        '    {"input": "<raw stdin string>", "expected_output": "<raw stdout string>"}\n'
        "  ],\n"
        '  "stress_inputs": [\n'
        '    "<raw stdin string at max constraints or large scale>"\n'
        "  ]\n"
        "}\n\n"
        "Instructions for edge_cases:\n"
        "Compute 2 to 3 tiny, tricky corner-case inputs (minimum N, zeroes, negative numbers, greedy counterexamples, "
        "32-bit overflow numbers near 2*10^9) by writing a simple brute-force oracle function in Python to calculate the exact expected_output. "
        "Do NOT guess math; let the Python script compute it.\n\n"
        "Instructions for stress_inputs:\n"
        "Generate 1 to 2 large-scale valid inputs (e.g., N = 5000 to 50000 depending on problem limits) programmatically using loops/random with "
        "a fixed seed (random.seed(42)) to test if the candidate code crashes or hits TLE.\n\n"
        "Output ONLY raw executable Python code. Do NOT wrap code in markdown backticks. Do NOT provide explanations. "
        "The script must print only the JSON output to stdout."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}"
    raw_response = await _call_ollama(full_prompt)
    try:
        return extract_clean_code(raw_response, "python")
    except Exception:
        pattern = re.compile(r"```(?:python)?\n(.*?)\n```", re.DOTALL)
        match = pattern.search(raw_response)
        if match:
            return match.group(1).strip()
        return raw_response.strip()

