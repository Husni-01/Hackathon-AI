import math
import asyncio
from typing import List, Optional, Dict, Tuple

try:
    from schemas import StreamEvent, TestCase
    from sandbox import execute_code, run_adversarial_generator, execute_stress_probe
    from utils.parser import extract_clean_code, truncate_error_trace, normalize_and_hash
    from llm_client import (
        generate_blueprints,
        generate_code_from_blueprint,
        generate_code_from_reflection,
        generate_reflection,
        generate_adversarial_harness,
    )
except ImportError:
    from backend.schemas import StreamEvent, TestCase
    from backend.sandbox import execute_code, run_adversarial_generator, execute_stress_probe
    from backend.utils.parser import extract_clean_code, truncate_error_trace, normalize_and_hash
    from backend.llm_client import (
        generate_blueprints,
        generate_code_from_blueprint,
        generate_code_from_reflection,
        generate_reflection,
        generate_adversarial_harness,
    )

class MCTSNode:
    def __init__(self, state_type: str, content: str, parent=None, code_snapshot: Optional[str] = None):
        self.state_type = state_type  # "root", "blueprint", "code", or "reflection"
        self.content = content
        self.parent = parent
        self.children = []
        self.visits = 0
        self.value = 0.0
        self.code_snapshot = code_snapshot or (parent.code_snapshot if parent else None)

    def ucb1(self) -> float:
        if self.visits == 0:
            return float('inf')
        return (self.value / self.visits) + 1.414 * math.sqrt(math.log(self.parent.visits) / self.visits) if self.parent else 0.0

def _get_problem(node: MCTSNode) -> str:
    curr = node
    while curr is not None:
        if curr.state_type == "root":
            return curr.content
        curr = curr.parent
    return ""

async def run_mcts(problem: str, language: str, max_iterations: int, timeout: int, test_cases: List[TestCase]):
    root = MCTSNode(state_type="root", content=problem)
    # AST Hash cache to avoid duplicate sandbox evaluation
    code_cache: Dict[str, Tuple[Dict, Optional[Dict]]] = {}

    yield f"data: {StreamEvent(event_type='status', message='Initializing Multi-Agent MCTS root node...').model_dump_json()}\n\n"

    try:
        # Pre-Loop Blueprint Generation with Handbook RAG
        yield f"data: {StreamEvent(event_type='status', message='Architect generating algorithmic blueprints with Handbook RAG...').model_dump_json()}\n\n"
        blueprints = await generate_blueprints(problem)
        for bp in blueprints:
            child = MCTSNode(state_type="blueprint", content=bp, parent=root)
            root.children.append(child)

        # Pre-Loop Adversary Suite Generation
        yield f"data: {StreamEvent(event_type='status', message='Adversary Agent: Generating corner cases and max-constraint stress probes...').model_dump_json()}\n\n"
        generator_code = await generate_adversarial_harness(problem)
        adv_suite = await run_adversarial_generator(generator_code, timeout_seconds=5)
        adv_edge_cases = adv_suite.get("edge_cases", [])
        adv_stress_inputs = adv_suite.get("stress_inputs", [])
        yield f"data: {StreamEvent(event_type='status', message=f'Adversary Agent synthesized {len(adv_edge_cases)} corner cases and {len(adv_stress_inputs)} stress probes.').model_dump_json()}\n\n"
    except Exception as e:
        yield f"data: {StreamEvent(event_type='error', message=str(e)).model_dump_json()}\n\n"
        return

    # Combine public test cases with adversarial edge cases for Stage A
    combined_cases = [{"input": tc.input, "expected_output": tc.expected_output} for tc in test_cases]
    for ec in adv_edge_cases:
        combined_cases.append({"input": ec["input"], "expected_output": ec["expected_output"]})

    for iteration in range(1, max_iterations + 1):
        # Hardware Thermal Pacing: cooldown for host copper heat-pipes
        await asyncio.sleep(1.2)

        # Selection
        node = root
        while node.children:
            unvisited = [c for c in node.children if c.visits == 0]
            if unvisited:
                node = unvisited[0]
                break
            node = max(node.children, key=lambda n: n.ucb1())

        # Expansion / Generation
        reward = 0.0
        clean_code = None
        error_msg = None
        curr = None

        try:
            if node.state_type == "root":
                yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Architect expanding blueprints...', iteration=iteration).model_dump_json()}\n\n"
                blueprints = await generate_blueprints(node.content)
                for bp in blueprints:
                    child = MCTSNode(state_type="blueprint", content=bp, parent=node)
                    node.children.append(child)
                reward = 0.0
                curr = node

            elif node.state_type == "blueprint" or node.state_type == "reflection":
                prob = _get_problem(node)

                if node.state_type == "blueprint":
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Coder implementing blueprint...', iteration=iteration).model_dump_json()}\n\n"
                    raw_code = await generate_code_from_blueprint(prob, node.content, language, test_cases=test_cases)
                else:
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Coder implementing surgical reflection repair...', iteration=iteration).model_dump_json()}\n\n"
                    failed_code = node.code_snapshot or ""
                    raw_code = await generate_code_from_reflection(
                        prob,
                        failed_code=failed_code,
                        reflection=node.content,
                        language=language,
                        test_cases=test_cases
                    )

                clean_code = extract_clean_code(raw_code, language)
                child = MCTSNode(state_type="code", content=clean_code, parent=node, code_snapshot=clean_code)
                node.children.append(child)

                # --- AST Hashing & Code Cache Deduplication ---
                code_hash = normalize_and_hash(clean_code, language)
                if code_hash in code_cache:
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: AST duplicate identified. Reusing cached sandbox results.', iteration=iteration).model_dump_json()}\n\n"
                    sandbox_res, stress_res = code_cache[code_hash]
                else:
                    # Stage A: Public + Adversarial Edge Cases
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Simulating in Sandbox (Stage A: Public & Edge Cases)...', iteration=iteration).model_dump_json()}\n\n"
                    sandbox_res = await execute_code(language, clean_code, combined_cases, timeout)

                    # Circuit Breaker: Halt immediately if Docker infrastructure fails
                    if sandbox_res.get("infra_error"):
                        err_detail = sandbox_res.get("error", "Unknown failure")
                        yield f"data: {StreamEvent(event_type='error', message=f'Sandbox Circuit Breaker: {err_detail}').model_dump_json()}\n\n"
                        return

                    stress_res = None
                    if sandbox_res["all_passed"] and adv_stress_inputs:
                        yield f"data: {StreamEvent(event_type='status', message='Public & edge cases passed! Running Adversary Max-Constraint Stress Probe...', iteration=iteration).model_dump_json()}\n\n"
                        stress_res = await execute_stress_probe(language, clean_code, adv_stress_inputs, timeout)

                    code_cache[code_hash] = (sandbox_res, stress_res)

                passed_count = sandbox_res["passed_count"]
                total_cases = sandbox_res["total_cases"]

                if sandbox_res["all_passed"]:
                    if stress_res is not None and not stress_res["survived"]:
                        passed = False
                        reward = 0.75  # Passed all edge cases, reward high to encourage refining for stress
                        error_msg = f"Failed Adversary Stress Probe: {stress_res['error']}"
                    else:
                        passed = True
                        reward = 1.0
                        error_msg = None
                else:
                    passed = False
                    if sandbox_res.get("error") and "Compilation Error" in sandbox_res["error"]:
                        reward = 0.0
                    elif sandbox_res.get("error") and "Runtime Error" in sandbox_res["error"]:
                        reward = 0.2
                    else:
                        ratio = passed_count / total_cases if total_cases > 0 else 0
                        reward = 0.2 + 0.6 * ratio
                    error_msg = sandbox_res.get("error")

                msg = f"Score: {reward:.2f}. Passed {passed_count}/{total_cases}"
                if not passed and error_msg:
                    clean_err = error_msg.split('\n')[0] if '\n' in error_msg else error_msg
                    msg = f"Score: {reward:.2f}. Passed {passed_count}/{total_cases}. ({clean_err})"
                elif passed:
                    msg = f"Score: 1.00. Passed all {passed_count}/{total_cases} tests & Stress Probes!"

                yield f"data: {StreamEvent(event_type='sandbox_result', message=msg, passed=passed, iteration=iteration, code_snippet=clean_code).model_dump_json()}\n\n"

                if passed:
                    yield f"data: {StreamEvent(event_type='final_solution', message='MCTS found optimal solution passing all public, adversarial, and stress tests!', code_snippet=clean_code).model_dump_json()}\n\n"
                    break

                if error_msg:
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Critic generating reflection...', iteration=iteration).model_dump_json()}\n\n"
                    diagnostic_context = error_msg
                    if sandbox_res.get("failed_case"):
                        fc = sandbox_res["failed_case"]
                        diagnostic_context += (
                            f"\nFailing Input:\n{fc.get('input', '')}\n"
                            f"Expected Output:\n{fc.get('expected_output', '')}\n"
                            f"Actual Output:\n{fc.get('actual_output', '')}\n"
                        )
                    reflection_text = await generate_reflection(prob, clean_code, truncate_error_trace(diagnostic_context))
                    ref_child = MCTSNode(state_type="reflection", content=reflection_text, parent=child, code_snapshot=clean_code)
                    child.children.append(ref_child)

                curr = child

            elif node.state_type == "code":
                reward = 0.0
                curr = node

        except Exception as e:
            reward = 0.0
            yield f"data: {StreamEvent(event_type='sandbox_result', message=f'Pipeline Error: {str(e)}', passed=False, iteration=iteration).model_dump_json()}\n\n"
            curr = node

        # Backpropagation
        while curr is not None:
            curr.visits += 1
            curr.value += reward
            curr = curr.parent
