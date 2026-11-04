import ast
import re
import hashlib

def extract_clean_code(raw_llm_output: str, language: str) -> str:
    """
    Extracts executable code from LLM responses, stripping Markdown code fences.
    Falls back to raw output if fences are absent. Validates Python AST if applicable.
    """
    pattern = re.compile(r"```(?:" + re.escape(language) + r")?[\r\n]+(.*?)[\r\n]+```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(raw_llm_output)
    if match:
        code = match.group(1).strip()
    else:
        # Check if generic code block is present
        gen_pattern = re.compile(r"```\w*[\r\n]+(.*?)[\r\n]+```", re.DOTALL)
        gen_match = gen_pattern.search(raw_llm_output)
        if gen_match:
            code = gen_match.group(1).strip()
        else:
            code = raw_llm_output.strip()

    if language.lower() in ("python", "py"):
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise ValueError(f"SyntaxError in generated Python code: {e.msg} at line {e.lineno}")

    return code


def truncate_error_trace(error_msg: str, max_chars: int = 600) -> str:
    """
    Truncates runtime error traces while preserving the tail where exception types
    and relevant stack lines reside.
    """
    if not error_msg:
        return ""
    if len(error_msg) <= max_chars:
        return error_msg
    truncated = error_msg[-max_chars:]
    return f"...[truncated]...\n{truncated}"


def normalize_and_hash(code: str, language: str) -> str:
    """
    Produces a deterministic SHA-256 hash of normalized code to detect semantic duplicates.
    - Python: canonicalized AST via ast.unparse(ast.parse(code)), eliminating formatting/comments.
    - C++: collapses consecutive whitespace and strips leading/trailing space.
    """
    clean = code.strip()
    if language.lower() in ("python", "py"):
        try:
            tree = ast.parse(clean)
            canonical = ast.unparse(tree)
        except Exception:
            canonical = re.sub(r'\s+', ' ', clean)
    else:
        canonical = re.sub(r'\s+', ' ', clean)

    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def estimate_required_complexity(problem_text: str) -> str:
    """
    Estimates required asymptotic time complexity from problem constraints based on
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
        return "O(n log n) or O(n) assumed."

    n = max(found_values)

    if n <= 20:
        return f"O(2^n) or O(n!) - Suggest Complete Search or Backtracking (N <= {n})."
    elif n <= 500:
        return f"O(n^3) - Suggest Floyd-Warshall or 3D Dynamic Programming (N <= {n})."
    elif n <= 5000:
        return f"O(n^2) - Suggest 2D Dynamic Programming or Nested Loops (N <= {n})."
    elif n <= 10**5:
        return f"O(n log n) or O(n) - Suggest Segment Trees, Binary Search, or Greedy (N <= {n})."
    else:
        return f"O(n log n) or O(n) - Suggest Coordinate Compression, Segment Trees, or O(1)/O(log n) per query (N <= {n})."
