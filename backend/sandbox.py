import docker
import base64
import time
import json
import asyncio
from typing import List, Dict, Optional, Tuple

client: Optional[docker.DockerClient] = None

def _get_client() -> docker.DockerClient:
    global client
    if client is None:
        client = docker.from_env()
    return client

class WarmWorkerManager:
    """
    Manages persistent singleton Docker containers per language with
    strict resource constraints and thermal limits (0.5 CPU core limit, cpuset_cpus 0,1).
    """
    _workers: Dict[str, Optional[docker.models.containers.Container]] = {
        "python": None,
        "cpp": None
    }
    _lock = asyncio.Lock()

    @classmethod
    async def get_worker(cls, language: str) -> docker.models.containers.Container:
        async with cls._lock:
            container = cls._workers.get(language)
            
            # Check if existing container is still alive and running
            if container is not None:
                try:
                    await asyncio.to_thread(container.reload)
                    if container.status == "running":
                        return container
                except Exception:
                    cls._workers[language] = None

            # Spawn a new warm container
            d_client = _get_client()
            image = "python:3.10-slim" if language == "python" else "gcc:12"
            container_name = f"hackathon_warm_{language}"

            # Ensure image is locally available
            try:
                await asyncio.to_thread(d_client.images.get, image)
            except docker.errors.ImageNotFound:
                await asyncio.to_thread(d_client.images.pull, image)

            # Cleanup any existing container with same name
            try:
                old = await asyncio.to_thread(d_client.containers.get, container_name)
                await asyncio.to_thread(old.remove, force=True)
            except Exception:
                pass

            # 256m tmpfs for cpp to hold precompiled stdc++.h.gch (~90MB), 64m for python
            tmpfs_size = "256m" if language == "cpp" else "64m"
            tmpfs = {"/tmp": f"rw,exec,nosuid,size={tmpfs_size}"}

            create_kwargs = {
                "image": image,
                "name": container_name,
                "command": ["sleep", "infinity"],
                "network_disabled": True,
                "mem_limit": "256m",
                "nano_cpus": 500_000_000,   # Strict 0.5 CPU core limit to eliminate host overheating
                "cpuset_cpus": "0,1",        # Pin to cores 0 and 1
                "read_only": True,
                "tmpfs": tmpfs,
                "detach": True
            }

            container = await asyncio.to_thread(d_client.containers.create, **create_kwargs)
            await asyncio.to_thread(container.start)

            # Precompile <bits/stdc++.h> once into /tmp/bits/stdc++.h.gch using -O1 for low CPU overhead
            if language == "cpp":
                pch_cmd = (
                    "mkdir -p /tmp/bits && "
                    "echo '#include <bits/stdc++.h>' > /tmp/bits/stdc++.h && "
                    "g++ -std=c++17 -O1 -x c++-header /tmp/bits/stdc++.h -o /tmp/bits/stdc++.h.gch"
                )
                await asyncio.to_thread(container.exec_run, ["/bin/sh", "-c", pch_cmd])

            cls._workers[language] = container
            return container

    @classmethod
    async def cleanup_worker(cls, language: str):
        async with cls._lock:
            container = cls._workers.get(language)
            if container:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:
                    pass
                cls._workers[language] = None

    @classmethod
    async def cleanup_all(cls):
        for lang in list(cls._workers.keys()):
            await cls.cleanup_worker(lang)


def _inject_file_base64(container: docker.models.containers.Container, filename: str, content: str):
    """
    Safely injects text content into /tmp/{filename} inside read_only rootfs containers
    using base64 decoding directly into the exec-enabled tmpfs.
    """
    b64_str = base64.b64encode(content.encode("utf-8")).decode("ascii")
    cmd = f"echo '{b64_str}' | base64 -d > /tmp/{filename}"
    container.exec_run(["/bin/sh", "-c", cmd])


def _outputs_match(actual: str, expected: str, eps: float = 1e-9) -> bool:
    """
    Compares two whitespace-separated token outputs with floating-point tolerance eps (1e-9).
    """
    actual_tokens = actual.strip().split()
    expected_tokens = expected.strip().split()
    if len(actual_tokens) != len(expected_tokens):
        return False
    for a, b in zip(actual_tokens, expected_tokens):
        if a == b:
            continue
        try:
            fa = float(a)
            fb = float(b)
            if abs(fa - fb) <= eps * max(1.0, abs(fb)):
                continue
            return False
        except (ValueError, TypeError):
            return False
    return True


async def execute_code(language: str, code: str, test_cases: List[Dict[str, str]], timeout_seconds: int = 5) -> Dict:
    """
    Executes candidate code inside the warm Docker container using base64 exec injection
    and captures full 2>&1 stderr tracebacks.
    """
    filename = "solution.py" if language == "python" else "solution.cpp"

    try:
        container = await WarmWorkerManager.get_worker(language)
    except Exception as e:
        return {
            "all_passed": False,
            "passed_count": 0,
            "total_cases": len(test_cases),
            "error": f"Docker infrastructure error: {str(e)}",
            "failed_case": None,
            "infra_error": True
        }

    try:
        # Clean previous run artifacts while preserving /tmp/bits (precompiled headers)
        await asyncio.to_thread(
            container.exec_run,
            ["/bin/sh", "-c", "rm -f /tmp/solution* /tmp/input_* /tmp/out_* /tmp/error.txt /tmp/generator* /tmp/stress*"]
        )

        # Base64 inject candidate source code
        await asyncio.to_thread(_inject_file_base64, container, filename, code)

        # Compile C++ with -O1 and -I/tmp to leverage precompiled <bits/stdc++.h.gch>
        if language == "cpp":
            compile_cmd = ["/bin/sh", "-c", f"g++ -std=c++17 -O1 -I/tmp /tmp/{filename} -o /tmp/solution 2>&1"]
            exit_code, output = await asyncio.to_thread(container.exec_run, compile_cmd)
            if exit_code != 0:
                err_text = output.decode("utf-8", errors="replace").strip()
                return {
                    "all_passed": False,
                    "passed_count": 0,
                    "total_cases": len(test_cases),
                    "error": f"Compilation Error:\n{err_text}",
                    "failed_case": None,
                    "infra_error": False
                }

        passed_count = 0
        run_bin = f"python3 /tmp/{filename}" if language == "python" else "/tmp/solution"

        for i, tc in enumerate(test_cases):
            input_file = f"input_{i}.txt"
            await asyncio.to_thread(_inject_file_base64, container, input_file, tc["input"])

            # Capture stdout and stderr via 2>&1, teeing to /tmp/error.txt
            exec_cmd = [
                "/bin/sh", "-c",
                f"timeout {timeout_seconds}s {run_bin} < /tmp/{input_file} 2>&1 | tee /tmp/error.txt"
            ]
            exit_code, output = await asyncio.to_thread(container.exec_run, exec_cmd)
            out_str = output.decode("utf-8", errors="replace").strip()

            if exit_code == 124:
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": f"Time Limit Exceeded (> {timeout_seconds}s) on Test Case {i+1}",
                    "failed_case": {
                        "input": tc["input"],
                        "expected_output": tc["expected_output"],
                        "actual_output": "[Time Limit Exceeded]"
                    },
                    "infra_error": False
                }

            if exit_code != 0:
                clean_err = out_str.strip() or f"Process exited with non-zero exit code: {exit_code}"
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": f"Runtime Error (Code {exit_code}):\n{clean_err}",
                    "failed_case": {
                        "input": tc["input"],
                        "expected_output": tc["expected_output"],
                        "actual_output": f"[Runtime Error: {clean_err}]"
                    },
                    "infra_error": False
                }

            if not _outputs_match(out_str, tc["expected_output"]):
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": (
                        f"Wrong Output on Test Case {i+1}:\n"
                        f"Input: {tc['input'].strip()}\n"
                        f"Expected: {tc['expected_output'].strip()}\n"
                        f"Actual:   {out_str}"
                    ),
                    "failed_case": {
                        "input": tc["input"],
                        "expected_output": tc["expected_output"],
                        "actual_output": out_str
                    },
                    "infra_error": False
                }

            passed_count += 1

        return {
            "all_passed": True,
            "passed_count": passed_count,
            "total_cases": len(test_cases),
            "error": None,
            "failed_case": None,
            "infra_error": False
        }

    except Exception as e:
        return {
            "all_passed": False,
            "passed_count": 0,
            "total_cases": len(test_cases),
            "error": f"Sandbox Exception: {str(e)}",
            "failed_case": None,
            "infra_error": False
        }


async def run_adversarial_generator(generator_code: str, timeout_seconds: int = 5) -> dict:
    """
    Executes the Adversary's Python test generator inside the warm Python worker.
    """
    default_result = {"edge_cases": [], "stress_inputs": []}
    try:
        container = await WarmWorkerManager.get_worker("python")
    except Exception:
        return default_result

    try:
        filename = "generator.py"
        await asyncio.to_thread(_inject_file_base64, container, filename, generator_code)

        exec_cmd = ["/bin/sh", "-c", f"timeout {timeout_seconds}s python3 /tmp/{filename} 2>&1"]
        exit_code, output = await asyncio.to_thread(container.exec_run, exec_cmd)
        out_str = output.decode("utf-8", errors="replace").strip()

        if exit_code != 0 or not out_str:
            return default_result

        # Locate enclosing JSON brackets
        json_start = out_str.find("{")
        json_end = out_str.rfind("}")
        if json_start != -1 and json_end != -1 and json_end >= json_start:
            json_text = out_str[json_start:json_end+1]
        else:
            json_text = out_str

        data = json.loads(json_text)
        if not isinstance(data, dict):
            return default_result

        edge_cases = data.get("edge_cases", [])
        stress_inputs = data.get("stress_inputs", [])

        valid_edge_cases = []
        for ec in edge_cases:
            if isinstance(ec, dict) and "input" in ec and "expected_output" in ec:
                valid_edge_cases.append({
                    "input": str(ec["input"]),
                    "expected_output": str(ec["expected_output"])
                })

        valid_stress_inputs = [str(s) for s in stress_inputs if s is not None and str(s).strip()]
        return {
            "edge_cases": valid_edge_cases,
            "stress_inputs": valid_stress_inputs
        }
    except Exception:
        return default_result


async def execute_stress_probe(language: str, code: str, stress_inputs: list[str], timeout_seconds: int = 5) -> dict:
    """
    Executes large-scale stress inputs to probe for TLE, integer overflow crashes,
    recursion limits, or segmentation faults.
    """
    filename = "solution.py" if language == "python" else "solution.cpp"
    try:
        container = await WarmWorkerManager.get_worker(language)
    except Exception as e:
        return {
            "survived": False,
            "error": f"Warm worker unavailable: {str(e)}",
            "is_timeout": False,
            "failed_stress_index": None
        }

    try:
        await asyncio.to_thread(_inject_file_base64, container, filename, code)

        if language == "cpp":
            compile_cmd = ["/bin/sh", "-c", f"g++ -std=c++17 -O1 -I/tmp /tmp/{filename} -o /tmp/solution 2>&1"]
            exit_code, output = await asyncio.to_thread(container.exec_run, compile_cmd)
            if exit_code != 0:
                return {
                    "survived": False,
                    "error": f"Compilation Error:\n{output.decode('utf-8', errors='replace')}",
                    "is_timeout": False,
                    "failed_stress_index": None
                }

        run_bin = f"python3 /tmp/{filename}" if language == "python" else "/tmp/solution"

        for i, s_input in enumerate(stress_inputs):
            input_file = f"stress_input_{i}.txt"
            await asyncio.to_thread(_inject_file_base64, container, input_file, s_input)

            exec_cmd = ["/bin/sh", "-c", f"timeout {timeout_seconds}s {run_bin} < /tmp/{input_file} 2>&1"]
            exit_code, output = await asyncio.to_thread(container.exec_run, exec_cmd)
            out_str = output.decode("utf-8", errors="replace").strip()

            if exit_code == 124:
                return {
                    "survived": False,
                    "error": f"Time Limit Exceeded (> {timeout_seconds}s) on stress input {i+1}",
                    "is_timeout": True,
                    "failed_stress_index": i
                }

            if exit_code != 0:
                return {
                    "survived": False,
                    "error": f"Runtime Crash (Code {exit_code}) on stress input {i+1}: {out_str}",
                    "is_timeout": False,
                    "failed_stress_index": i
                }

            if not out_str:
                return {
                    "survived": False,
                    "error": f"Empty Output on stress input {i+1}",
                    "is_timeout": False,
                    "failed_stress_index": i
                }

        return {
            "survived": True,
            "error": None,
            "is_timeout": False,
            "failed_stress_index": None
        }

    except Exception as e:
        return {
            "survived": False,
            "error": f"Stress probe exception: {str(e)}",
            "is_timeout": False,
            "failed_stress_index": None
        }
