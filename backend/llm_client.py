import os
import httpx
import re
import json

try:
    from utils.parser import estimate_required_complexity, extract_clean_code
    from utils.handbook_rag import retrieve_handbook_guidance
except ImportError:
    from backend.utils.parser import estimate_required_complexity, extract_clean_code
    from backend.utils.handbook_rag import retrieve_handbook_guidance

OLLAMA_OPTIONS = {
    "num_ctx": 2048,
    "num_predict": 800,
    "temperature": 0.2,
    "num_thread": 3  # Cap Ollama CPU threads to prevent host thermal throttling
}

async def _call_llm(prompt: str) -> str:
    """
    Hybrid multi-provider LLM caller.
    Prioritizes GEMINI_API_KEY or GROQ_API_KEY when available;
    otherwise falls back to local Ollama (qwen2.5-coder:7b) with thermal pacing.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    if gemini_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
        }
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=60.0)
            res.raise_for_status()
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    elif groq_key:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {groq_key}"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1024
        }
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, headers=headers, timeout=60.0)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

    else:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "qwen2.5-coder:7b",
            "prompt": prompt,
            "stream": False,
            "options": OLLAMA_OPTIONS,
            "keep_alive": "30s"
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=120.0)
                response.raise_for_status()
                data = response.json()
                return data.get("response", "").strip()
            except httpx.ConnectError:
                raise RuntimeError(
                    "Ollama is not running on http://localhost:11434. "
                    "Please start Ollama by opening the Ollama application or running 'ollama serve' in a terminal."
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise RuntimeError(
                        "Ollama model 'qwen2.5-coder:7b' was not found. "
                        "Please download it by running: 'ollama pull qwen2.5-coder:7b'"
                    )
                raise RuntimeError(f"Ollama returned HTTP error {e.response.status_code}: {e.response.text}")


async def generate_blueprints(problem: str) -> list[str]:
    complexity_string = estimate_required_complexity(problem)
    handbook_rules = retrieve_handbook_guidance(problem)

    system_prompt = (
        "Act as a Senior Algorithm Architect & Competitive Programming Grandmaster.\n"
        "Your task is to output exactly 3 completely different, high-level algorithmic approaches "
        "to solve the problem (e.g., Coordinate Compression + Dijkstra vs. Floyd-Warshall vs. 2D DP).\n"
        "Do NOT write code.\n\n"
        f"TIME COMPLEXITY CONSTRAINT: {complexity_string}\n\n"
        f"AUTHORITATIVE HANDBOOK BLUEPRINTS & RULES (Antti Laaksonen's Competitive Programmer's Handbook):\n"
        f"{handbook_rules}\n\n"
        "Separate each approach with the exact delimiter '||BLUEPRINT||'."
    )
    full_prompt = f"{system_prompt}\n\nProblem Description:\n{problem}"
    response = await _call_llm(full_prompt)

    if "||BLUEPRINT||" in response:
        blueprints = [b.strip() for b in response.split("||BLUEPRINT||") if b.strip()]
    else:
        splits = re.split(r'(?:\n|\A)(?:Approach\s+\d+|Option\s+\d+|\d+\.)[:\.\s]', response, flags=re.IGNORECASE)
        blueprints = [s.strip() for s in splits if s.strip()]

    if not blueprints:
        blueprints = [response.strip()]
    return blueprints[:3]


async def generate_code_from_blueprint(problem: str, blueprint: str, language: str, test_cases: list = None) -> str:
    template_instruction = ""
    if language.lower() in ("cpp", "c++"):
        template_instruction = (
            "\nWrap your logic inside this exact competitive programming template:\n"
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "typedef long long ll;\n"
            "const ll INF = 1e18;\n"
            "int main() {\n"
            "    ios::sync_with_stdio(0); cin.tie(0);\n"
            "    // Logic here\n"
            "    return 0;\n"
            "}"
        )

    sample_context = ""
    if test_cases:
        samples = []
        for i, tc in enumerate(test_cases[:3]):
            inp = tc.get("input", "") if isinstance(tc, dict) else getattr(tc, "input", "")
            out = tc.get("expected_output", "") if isinstance(tc, dict) else getattr(tc, "expected_output", "")
            if inp.strip() or out.strip():
                samples.append(f"Sample {i+1} Stdin:\n{inp.strip()}\nSample {i+1} Expected Stdout:\n{out.strip()}")
        if samples:
            sample_context = (
                "\n\nCRITICAL SAMPLE TEST CASES (Your code MUST strictly read from stdin in this exact format and produce this stdout):\n"
                + "\n\n".join(samples)
            )

    system_prompt = (
        f"Act as an expert Coder. Given the problem and this specific mathematical blueprint, "
        f"write the highly optimized implementation in {language}. Output ONLY raw code. "
        f"Do NOT wrap code in markdown backticks. Do NOT provide explanations.{template_instruction}\n"
        f"RULES FOR ZERO-ERROR CODE:\n"
        f"1. Standard Input Parsing: Read tokens from stdin (sys.stdin.read().split() or cin) matching the exact structure of the sample test cases.\n"
        f"2. Integer Safety: Use 64-bit integers (`long long` in C++) for all coordinates, distances, and costs to prevent 32-bit overflow.\n"
        f"3. Shortest Paths: Use `INF = 1e18` (never LLONG_MAX) so `dist + w` does not overflow."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}{sample_context}\n\nBlueprint / Instructions:\n{blueprint}"
    return await _call_llm(full_prompt)


async def generate_code_from_reflection(
    problem: str,
    failed_code: str,
    reflection: str,
    language: str,
    test_cases: list = None
) -> str:
    """
    Passes previous failed code, exact Critic reflection, and sample test cases
    to the Coder agent to perform direct surgical repairs.
    """
    template_instruction = ""
    if language.lower() in ("cpp", "c++"):
        template_instruction = (
            "\nWrap your logic inside this exact competitive programming template:\n"
            "#include <bits/stdc++.h>\n"
            "using namespace std;\n"
            "typedef long long ll;\n"
            "const ll INF = 1e18;\n"
            "int main() {\n"
            "    ios::sync_with_stdio(0); cin.tie(0);\n"
            "    // Logic here\n"
            "    return 0;\n"
            "}"
        )

    sample_context = ""
    if test_cases:
        samples = []
        for i, tc in enumerate(test_cases[:3]):
            inp = tc.get("input", "") if isinstance(tc, dict) else getattr(tc, "input", "")
            out = tc.get("expected_output", "") if isinstance(tc, dict) else getattr(tc, "expected_output", "")
            if inp.strip() or out.strip():
                samples.append(f"Sample {i+1} Stdin:\n{inp.strip()}\nSample {i+1} Expected Stdout:\n{out.strip()}")
        if samples:
            sample_context = (
                "\n\nCRITICAL SAMPLE TEST CASES:\n"
                + "\n\n".join(samples)
            )

    system_prompt = (
        f"Act as an expert Coder. You are repairing a previous solution in {language} that failed in testing.\n"
        f"Output ONLY the complete raw corrected code. Do NOT wrap code in markdown backticks. Do NOT explain.{template_instruction}\n"
        f"RULES FOR ZERO-ERROR CODE:\n"
        f"1. Directly apply all corrections specified in the Critic's reflection.\n"
        f"2. Ensure standard input parsing precisely matches the stdin token stream.\n"
        f"3. Use 64-bit integers (`long long` in C++) for all distances, costs, and intermediate arithmetic."
    )
    full_prompt = (
        f"{system_prompt}\n\n"
        f"Problem Description:\n{problem}{sample_context}\n\n"
        f"Previous Failing Code:\n{failed_code}\n\n"
        f"Critic Reflection & Fix Instructions:\n{reflection}"
    )
    return await _call_llm(full_prompt)


async def generate_reflection(problem: str, failed_code: str, sandbox_error: str) -> str:
    system_prompt = (
        "Act as a strict Code Critic & Competitive Programming Judge. The Coder's implementation failed the sandbox tests.\n"
        "Analyze the `failed_code` and the `sandbox_error`.\n"
        "1. If there is a Runtime Error (like IndexError, ValueError, or parsing crash), pinpoint the exact line where stdin reading or indexing failed and dictate the exact stdin parser.\n"
        "2. If there is a Wrong Output (Input vs Expected vs Actual), deduce where the logic or coordinate arithmetic deviated from the problem specifications.\n"
        "3. If there is TLE, dictate coordinate compression or asymptotic pruning.\n"
        "Dictate clearly and concisely how the Coder must rewrite the algorithm in the next iteration."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}\n\nFailed Code:\n{failed_code}\n\nSandbox Diagnostic:\n{sandbox_error}"
    return await _call_llm(full_prompt)


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
        "Compute 2 to 3 tricky corner-case inputs (minimum bounds, zeroes, negatives, 32-bit overflow numbers near 2*10^9) "
        "by writing a small brute-force oracle function in Python to calculate the exact expected_output. "
        "Do NOT guess math; let the Python script calculate it.\n\n"
        "Instructions for stress_inputs:\n"
        "Generate 1 to 2 large-scale valid inputs (e.g., N = 10000 to 50000) programmatically using loops with random.seed(42) "
        "to test if the candidate code crashes or hits TLE.\n\n"
        "Output ONLY raw executable Python code. Do NOT wrap code in markdown backticks. Do NOT provide explanations. "
        "The script must print only the JSON output to stdout."
    )
    full_prompt = f"{system_prompt}\n\nProblem:\n{problem}"
    raw_response = await _call_llm(full_prompt)
    try:
        return extract_clean_code(raw_response, "python")
    except Exception:
        pattern = re.compile(r"```(?:python)?\n(.*?)\n```", re.DOTALL)
        match = pattern.search(raw_response)
        if match:
            return match.group(1).strip()
        return raw_response.strip()
