import math
from typing import List, Optional
from schemas import StreamEvent, TestCase
from sandbox import execute_code, run_adversarial_generator, execute_stress_probe
from utils.parser import extract_clean_code, truncate_error_trace
from llm_client import (
    generate_blueprints,
    generate_code_from_blueprint,
    generate_reflection,
    generate_adversarial_harness,
)

class MCTSNode:
    def __init__(self, state_type: str, content: str, parent=None):
        self.state_type = state_type # "root", "blueprint", "code", or "reflection"
        self.content = content
        self.parent = parent
        self.children = []
        self.visits = 0
        self.value = 0.0

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

def _get_blueprint_context(node: MCTSNode) -> str:
    if node.state_type == "blueprint":
        return node.content
    elif node.state_type == "reflection":
        curr = node.parent
        bp_content = ""
        while curr is not None:
            if curr.state_type == "blueprint":
                bp_content = curr.content
                break
            curr = curr.parent
        if bp_content:
            return f"Algorithmic Blueprint:\n{bp_content}\n\nCritic Reflection & Rewrite Guidance:\n{node.content}"
        return node.content
    return node.content

async def run_mcts(problem: str, language: str, max_iterations: int, timeout: int, test_cases: List[TestCase]):
    root = MCTSNode(state_type="root", content=problem)
    yield f"data: {StreamEvent(event_type='status', message='Initializing Multi-Agent MCTS root node...').model_dump_json()}\n\n"
    
    # Pre-Loop Blueprint Generation
    yield f"data: {StreamEvent(event_type='status', message='Architect generating blueprints...').model_dump_json()}\n\n"
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

    # Combine public test cases with adversarial edge cases for Stage A
    combined_cases = [{"input": tc.input, "expected_output": tc.expected_output} for tc in test_cases]
    for ec in adv_edge_cases:
        combined_cases.append({"input": ec["input"], "expected_output": ec["expected_output"]})

    for iteration in range(1, max_iterations + 1):
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
                yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Architect generating blueprints...', iteration=iteration).model_dump_json()}\n\n"
                blueprints = await generate_blueprints(node.content)
                for bp in blueprints:
                    child = MCTSNode(state_type="blueprint", content=bp, parent=node)
                    node.children.append(child)
                reward = 0.0
                curr = node
                
            elif node.state_type == "blueprint" or node.state_type == "reflection":
                role = "Coder implementing blueprint" if node.state_type == "blueprint" else "Coder implementing reflection"
                yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: {role}...', iteration=iteration).model_dump_json()}\n\n"
                
                prob = _get_problem(node)
                blueprint_context = _get_blueprint_context(node)
                raw_code = await generate_code_from_blueprint(prob, blueprint_context, language)
                clean_code = extract_clean_code(raw_code, language)
                
                child = MCTSNode(state_type="code", content=clean_code, parent=node)
                node.children.append(child)
                
                # --- Two-Stage Evaluation ---
                # Stage A: Public + Adversarial Edge Cases
                yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Simulating in Sandbox (Stage A: Public & Edge Cases)...', iteration=iteration).model_dump_json()}\n\n"
                sandbox_res = await execute_code(language, clean_code, combined_cases, timeout)
                
                passed_count = sandbox_res["passed_count"]
                total_cases = sandbox_res["total_cases"]
                
                if sandbox_res["all_passed"]:
                    # Stage B: Max-Constraint Stress Probe
                    if adv_stress_inputs:
                        yield f"data: {StreamEvent(event_type='status', message='Public & edge cases passed! Running Adversary Max-Constraint Stress Probe...', iteration=iteration).model_dump_json()}\n\n"
                        stress_res = await execute_stress_probe(language, clean_code, adv_stress_inputs, timeout)
                        if not stress_res["survived"]:
                            passed = False
                            reward = 0.75
                            error_msg = f"Failed Adversary Stress Probe (TLE/Overflow/Crash): {stress_res['error']}"
                        else:
                            passed = True
                            reward = 1.0
                            error_msg = None
                    else:
                        passed = True
                        reward = 1.0
                        error_msg = None
                else:
                    passed = False
                    if sandbox_res["error"] and "Compilation Error" in sandbox_res["error"]:
                        reward = 0.0
                    elif sandbox_res["error"] and "Runtime Error" in sandbox_res["error"]:
                        reward = 0.2
                    else:
                        ratio = passed_count / total_cases if total_cases > 0 else 0
                        reward = 0.2 + 0.6 * ratio
                    error_msg = sandbox_res["error"]
                
                msg = f"Score: {reward:.2f}. Passed {passed_count}/{total_cases}"
                if not passed and error_msg and "Failed Adversary Stress Probe" in error_msg:
                    msg = f"Score: 0.75. Passed {passed_count}/{total_cases} tests but {error_msg}"
                elif passed:
                    msg = f"Score: 1.00. Passed all {passed_count}/{total_cases} tests & Stress Probes!"

                yield f"data: {StreamEvent(event_type='sandbox_result', message=msg, passed=passed, iteration=iteration, code_snippet=clean_code).model_dump_json()}\n\n"
                
                if passed:
                    yield f"data: {StreamEvent(event_type='final_solution', message='MCTS found optimal solution passing all public, adversarial, and stress tests!', code_snippet=clean_code).model_dump_json()}\n\n"
                    break
                    
                if error_msg:
                    yield f"data: {StreamEvent(event_type='status', message=f'Iteration {iteration}: Critic generating reflection...', iteration=iteration).model_dump_json()}\n\n"
                    reflection_text = await generate_reflection(prob, clean_code, truncate_error_trace(error_msg))
                    ref_child = MCTSNode(state_type="reflection", content=reflection_text, parent=child)
                    child.children.append(ref_child)
                    
                curr = child
                
            elif node.state_type == "code":
                reward = 0.0
                curr = node
                
        except Exception as e:
            reward = 0.0
            yield f"data: {StreamEvent(event_type='sandbox_result', message=f'LLM or Sandbox Error: {str(e)}', passed=False, iteration=iteration).model_dump_json()}\n\n"
            curr = node
            
        # Backpropagation
        while curr is not None:
            curr.visits += 1
            curr.value += reward
            curr = curr.parent
