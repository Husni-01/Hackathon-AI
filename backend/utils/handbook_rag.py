import os
import re
from typing import Optional

_HANDBOOK_CACHE: Optional[str] = None

def _get_handbook_text() -> str:
    """
    Attempts to read text from Hackathon book.pdf or Hackathon book_2.pdf if available.
    Caches the extracted text in memory for zero-latency algorithmic retrieval.
    """
    global _HANDBOOK_CACHE
    if _HANDBOOK_CACHE is not None:
        return _HANDBOOK_CACHE

    # Search project root and nearby paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        "Hackathon book.pdf",
        "Hackathon book_2.pdf",
        os.path.join(base_dir, "..", "..", "Hackathon book.pdf"),
        os.path.join(base_dir, "..", "..", "Hackathon book_2.pdf"),
        os.path.join(base_dir, "..", "Hackathon book.pdf"),
    ]

    for fname in candidates:
        if os.path.exists(fname):
            try:
                import pypdf
                reader = pypdf.PdfReader(fname)
                extracted = []
                for i in range(min(len(reader.pages), 40)):
                    txt = reader.pages[i].extract_text() or ""
                    if txt:
                        extracted.append(txt)
                _HANDBOOK_CACHE = "\n".join(extracted)
                return _HANDBOOK_CACHE
            except Exception:
                pass

    _HANDBOOK_CACHE = ""
    return _HANDBOOK_CACHE


def retrieve_handbook_guidance(problem: str) -> str:
    """
    Analyzes the problem description and produces authoritative competitive programming
    rules and algorithmic blueprints based on Antti Laaksonen's Competitive Programmer's Handbook.
    """
    # Prime handbook text cache if available
    _get_handbook_text()

    guidelines = []
    prob_lower = problem.lower()

    # 1. Sparse Coordinates / Multi-dimensional Grid / Wormholes (Ch 9.4 & Ch 13)
    has_large_coords = bool(re.search(r"(?:10\^[6-9]|10\^\{[6-9]\}|1000000|1e[6-9]|\bgrid\b|\bwormhole\b|\bportal\b|\bcoordinates?\b|\bpoints?\b)", problem, re.I))
    if has_large_coords or "wormhole" in prob_lower or "grid" in prob_lower or "coordinate" in prob_lower:
        guidelines.append(
            "- [Handbook Ch 9.4 & Ch 13 - Coordinate Compression & Sparse Graphs]:\n"
            "  The grid/coordinate space is far too large for a standard 2D/3D matrix. "
            "  Compress active coordinates: map all special points, wormhole endpoints, source and destination nodes "
            "  to contiguous unique IDs (0..M-1). Construct an adjacency graph exclusively among these compressed vertices, "
            "  then execute Dijkstra's Algorithm or Floyd-Warshall over the compressed state space."
        )

    # 2. Shortest Paths & 64-bit INF Bounds (Ch 1.3 & Ch 13)
    has_graph_or_queries = bool(re.search(r"(\bgraph\b|\bshortest path\b|\bdijkstra\b|\bqueries\b|\bfuel\b|\bcost\b|\bdist\b|\bvertices\b)", problem, re.I))
    if has_graph_or_queries or "dijkstra" in prob_lower or "min_cost" in prob_lower:
        guidelines.append(
            "- [Handbook Ch 1.3 & Ch 13 - Shortest Paths & Safe Relaxation]:\n"
            "  Always define `const ll INF = 1e18;` (or `1LL << 60`). NEVER use `LLONG_MAX` or unchecked infinity, "
            "  as `INF + weight` will overflow into negative values and corrupt relaxation steps. "
            "  In Dijkstra min-heaps, always verify `if (d > dist[u]) continue;` to avoid redundant edge expansions."
        )

    # 3. Dynamic Programming & Modular Arithmetic (Ch 6 & Ch 7)
    if re.search(r"(\bmod\b|10\^9\s*\+\s*7|1000000007|998244353|\bways\b|\bcombinations?\b|\bdp\b)", problem, re.I):
        guidelines.append(
            "- [Handbook Ch 6 & Ch 7 - Dynamic Programming & Modulo Safety]:\n"
            "  Every state transition must be explicit.\n"
            "  - Addition: `(a + b) % MOD`\n"
            "  - Multiplication: `(1LL * a * b) % MOD` (cast to 64-bit before multiplying)\n"
            "  - Subtraction: always handle negative remainders via `(a - b % MOD + MOD) % MOD`."
        )

    # 4. Range Queries & Dynamic Updates (Ch 9)
    if re.search(r"(\brange sum\b|\brange query\b|\bsegment tree\b|\bfenwick\b|\bbinary indexed tree\b|\binterval\b)", problem, re.I):
        guidelines.append(
            "- [Handbook Ch 9 - Range Queries]:\n"
            "  For dynamic prefix/point updates with range sums, implement a Fenwick Tree (Binary Indexed Tree) using `k += k & -k` "
            "  or an iterative Segment Tree for clean O(log n) queries and minimal cache misses."
        )

    # 5. Tree XOR & Bitwise Contribution (Ch 10 & Ch 14)
    if re.search(r"(\btree\b|\bxor\b|\bbitwise\b|\bpath xor\b)", problem, re.I):
        guidelines.append(
            "- [Handbook Ch 10 & Ch 14 - Tree XOR & Bitwise Contribution]:\n"
            "  On trees, the XOR sum along the path between vertices u and v satisfies `path_xor(u, v) = pref[u] ^ pref[v]`, "
            "  where `pref[x]` is the XOR sum from root to x precomputed via a single DFS in O(N). "
            "  For all-pairs XOR sums or path aggregates, decompose bit-by-bit (0..60) and count the contribution of each bit independently in O(N)."
        )

    # 6. Universal Standard Rules & 64-Bit Mandates (Ch 1.3)
    guidelines.append(
        "- [Handbook Ch 1.3 - Universal Robustness Rules]:\n"
        "  1. 64-bit Integers: Mandate `long long` for all costs, distances, coordinates, and intermediate sums to prevent 32-bit overflow.\n"
        "  2. Standard Input: Read tokens directly (e.g. `sys.stdin.read().split()` or `cin >>`) matching the exact token sequence.\n"
        "  3. Fast I/O: For C++, use `ios::sync_with_stdio(0); cin.tie(0);` and `\\n` instead of `endl`."
    )

    return "\n\n".join(guidelines)
