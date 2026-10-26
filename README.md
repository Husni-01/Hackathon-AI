# 🚀 Hackathon AI

> An advanced, high-performance platform engineered to accelerate hackathon prototyping, automated code generation, and competitive programming solutions. Powered by modern web architectures (**React** & **Node.js/Python**) and grounded in rigorous algorithmic theory from the *Competitive Programmer's Handbook*[cite: 5].

---

## 📑 Table of Contents

1. [About The Project](#-about-the-project)
2. [Theoretical Foundation](#-theoretical-foundation)
3. [Architecture & Tech Stack](#-architecture--tech-stack)
4. [Project Directory Structure](#-project-directory-structure)
5. [Core Algorithmic Modules](#-core-algorithmic-modules)
6. [Getting Started & Prerequisites](#-getting-started--prerequisites)
7. [Installation & Setup](#-installation--setup)
8. [Running the Application](#-running-the-application)
9. [API & Execution Flow](#-api--execution-flow)
10. [Contributing](#-contributing)
11. [License](#-license)

---

## 📖 About The Project

**Hackathon AI** is built for high-pressure development environments like hackathons and coding competitions. It combines a seamless, reactive user interface with a heavy-duty backend capable of parsing complex codebases, executing search algorithms (such as Monte Carlo Tree Search), and evaluating execution sandboxes. 

By integrating core principles of algorithm design and efficiency, Hackathon AI ensures that generated solutions are both functionally correct and optimized to pass strict execution time limits[cite: 15, 30].

---

## 📚 Theoretical Foundation

Hackathon AI's core computational engines are deeply influenced and powered by the methodologies outlined in the *Competitive Programmer's Handbook* by Antti Laaksonen[cite: 5]:
*   **Time Complexity Estimation:** Algorithms and generated patches are evaluated against strict scale parameters (e.g., handling $N = 10^5$ inputs within standard 1-second execution boundaries)[cite: 21, 30].
*   **Dynamic Programming:** Implements memoization and iterative state evaluation patterns derived from Chapter 7 to solve overlapping subproblems efficiently[cite: 65, 81].
*   **Graph Algorithms & Traversals:** Utilizes advanced graph representation, DFS/BFS, and shortest-path heuristics (such as Dijkstra's and Bellman-Ford algorithms) from Chapters 11–13[cite: 109, 117, 123].
*   **Complete Search & Pruning:** Incorporates backtracking and search tree pruning techniques to explore solution spaces effectively[cite: 50, 51].

---

## 🛠️ Architecture & Tech Stack

*   **Frontend Client:** 
    *   **Framework:** React (Next.js App Router structure)
    *   **Styling:** Modern CSS / Tailwind CSS
    *   **State Management:** React Hooks & Context API
*   **Backend Server:** 
    *   **Runtime:** Node.js / Express.js
    *   **Execution Core:** Python 3.x (handling compute-heavy logic, search trees, and LLM orchestration)
*   **Core Logic & Engines:**
    *   `mcts.py`: Monte Carlo Tree Search implementation for decision-making and path optimization.
    *   `sandbox.py`: Secure execution environment for testing code snippets.
    *   `llm_client.py`: Interface for AI model integrations.

---

## 📁 Project Structure

```text
Hackathon AI/
├── app/                  # Next.js / React application views and routes
├── backend/              # Python & Node.js backend execution core
│   ├── __pycache__/      # Python compiled bytecode
│   ├── utils/            # Helper scripts and numerical/string utilities
│   ├── llm_client.py     # Language Model communication client
│   ├── main.py           # Core backend entry point / API router
│   ├── mcts.py           # Monte Carlo Tree Search engine
│   ├── mcts_execution.log# Execution logs for search optimizations
│   ├── sandbox.py        # Isolated code sandbox environment
│   ├── schemas.py        # Pydantic / Data validation schemas
│   └── solve_file.py     # Automated problem solver module
├── frontend/             # Dedicated frontend components and assets
├── public/               # Static public assets (images, icons)
├── Hackathon book.PDF    # Core reference handbook for algorithmic patterns[cite: 5]
├── package.json          # Node.js dependencies and project metadata
├── next.config.ts        # Next.js framework configuration
├── tsconfig.json         # TypeScript compiler configuration
└── README.md             # Comprehensive project documentation
