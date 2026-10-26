import ast
import re

def extract_clean_code(raw_llm_output: str, language: str) -> str:
    # Try to extract from markdown code blocks
    pattern = re.compile(r"```(?:" + re.escape(language) + r")?\n(.*?)\n```", re.DOTALL)
    match = pattern.search(raw_llm_output)
    if match:
        code = match.group(1).strip()
    else:
        # Fallback to pure string
        code = raw_llm_output.strip()

    if language == "python":
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise ValueError(f"SyntaxError in generated Python code: {e.msg} at line {e.lineno}")

    return code

def truncate_error_trace(error_msg: str, max_chars: int = 500) -> str:
    if not error_msg:
        return ""
    if len(error_msg) <= max_chars:
        return error_msg
    # Focus on the tail where traceback exception types usually lie
    truncated = error_msg[-max_chars:]
    return f"...[truncated]...\n{truncated}"

def estimate_required_complexity(problem_text: str) -> str:
    """
    Estimates required time complexity from problem constraints based on
    Antti Laaksonen's Competitive Programmer's Handbook heuristics.
    """
    if not problem_text:
        return "O(n log n) assumed."

    def _parse_val(val_str: str):
        s = val_str.replace(",", "").replace("{", "").replace("}", "").strip()
        # Handle formats like 2 * 10^5, 2 \times 10^5, 2 \cdot 10^5
        m_mul = re.match(r'(\d+)\s*(?:\\times|\\cdot|\*)\s*10\^(\d+)', s)
        if m_mul:
            return int(m_mul.group(1)) * (10 ** int(m_mul.group(2)))
        # Handle 10^X
        m_pow = re.match(r'10\^(\d+)', s)
        if m_pow:
            return 10 ** int(m_pow.group(1))
        # Handle scientific notation e.g. 1e5
        m_exp = re.match(r'(\d+(?:\.\d+)?)[eE](\d+)', s)
        if m_exp:
            return int(float(m_exp.group(1)) * (10 ** int(m_exp.group(2))))
        # Handle plain integers
        m_int = re.match(r'(\d+)', s)
        if m_int:
            return int(m_int.group(1))
        return None

    patterns = [
        # Double inequality: 1 <= N <= 2000 or 1 \le n \le 10^5
        r'(?i)\d+\s*(?:\\le|\\leq|\\leqslant|<=|<)\s*[a-z_]\w*\s*(?:\\le|\\leq|\\leqslant|<=|<)\s*([0-9\^\{\}\\\*\s\.,\+]+)',
        # Single inequality: N <= 2000, N \le 10^5, N < 10^6
        r'(?i)(?:[a-z_]\w*|[nNmMkK])\s*(?:\\le|\\leq|\\leqslant|<=|<)\s*([0-9\^\{\}\\\*\s\.,\+]+)',
        # Formats like N = 10^5, N up to 10^5
        r'(?i)(?:[nNmMkK])\s*(?:=|up\s+to)\s*([0-9\^\{\}\\\*\s\.,\+]+)',
    ]

    found_values = []
    for pat in patterns:
        for match in re.finditer(pat, problem_text):
            parsed = _parse_val(match.group(1))
            if parsed is not None:
                found_values.append(parsed)

    if not found_values:
        for match in re.finditer(r'10\^\{?(\d+)\}?', problem_text):
            found_values.append(10 ** int(match.group(1)))

    if not found_values:
        return "O(n log n) assumed."

    n = max(found_values)

    if n <= 20:
        return "O(2^n) or O(n!) - Suggest Complete Search or Backtracking."
    elif n <= 500:
        return "O(n^3) - Suggest Floyd-Warshall or 3D DP."
    elif n <= 5000:
        return "O(n^2) - Suggest 2D DP or Nested Loops."
    elif n <= 10**5:
        return "O(n log n) or O(n) - Suggest Segment Trees, Binary Search, or Greedy."
    else:
        return "O(n log n) or O(n) - Suggest Segment Trees, Binary Search, or Greedy."

