import docker
import tarfile
import io
import time
import json
import asyncio
from typing import List, Dict, Optional

client = None
try:
    client = docker.from_env()
except Exception:
    pass

def _get_client():
    global client
    if client is None:
        client = docker.from_env()
    return client

def create_tar_archive(filename: str, content: str) -> bytes:
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode='w') as tar:
        encoded = content.encode('utf-8')
        tarinfo = tarfile.TarInfo(name=filename)
        tarinfo.size = len(encoded)
        tarinfo.mtime = int(time.time())
        tarinfo.mode = 0o777
        tar.addfile(tarinfo=tarinfo, fileobj=io.BytesIO(encoded))
    tar_stream.seek(0)
    return tar_stream.read()

def _outputs_match(actual: str, expected: str, eps: float = 1e-9) -> bool:
    """
    Compares two whitespace-separated token outputs with floating-point tolerance eps.
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
    image = "python:3.10-slim" if language == "python" else "gcc:12"
    filename = "solution.py" if language == "python" else "solution.cpp"
    
    d_client = _get_client()
    try:
        d_client.images.get(image)
    except docker.errors.ImageNotFound:
        d_client.images.pull(image)

    # Temporary filesystem constraints
    tmpfs = {"/tmp": "rw,noexec,nosuid,size=64m"}
    if language == "cpp":
        tmpfs = {"/tmp": "rw,nosuid,size=64m"}
        
    container = None
    try:
        container = d_client.containers.create(
            image,
            command="sleep infinity",
            network_disabled=True,
            mem_limit="128m",
            read_only=True,
            tmpfs=tmpfs,
            detach=True
        )
        container.start()
        
        # Inject code via in-memory tar stream
        container.put_archive("/tmp", create_tar_archive(filename, code))
        
        if language == "cpp":
            compile_cmd = ["g++", "-O2", f"/tmp/{filename}", "-o", "/tmp/solution"]
            exit_code, output = await asyncio.to_thread(container.exec_run, compile_cmd)
            if exit_code != 0:
                return {
                    "all_passed": False,
                    "passed_count": 0,
                    "total_cases": len(test_cases),
                    "error": f"Compilation Error:\n{output.decode('utf-8', errors='replace')}",
                    "failed_case": None
                }

        passed_count = 0
        for i, tc in enumerate(test_cases):
            run_cmd = ["python3", f"/tmp/{filename}"] if language == "python" else ["/tmp/solution"]
            
            input_file = f"input_{i}.txt"
            container.put_archive("/tmp", create_tar_archive(input_file, tc["input"]))
            
            exec_run_cmd = ["timeout", f"{timeout_seconds}s", "sh", "-c", f"{run_cmd[0]} {run_cmd[1] if len(run_cmd)>1 else ''} < /tmp/{input_file}"]
            exit_code, output = await asyncio.to_thread(container.exec_run, exec_run_cmd)
            out_str = output.decode('utf-8', errors='replace').strip()
            
            if exit_code == 124:
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": f"Time Limit Exceeded (Code 124, >{timeout_seconds}s)",
                    "failed_case": tc
                }
            if exit_code != 0:
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": f"Runtime Error (Code {exit_code}):\n{out_str}",
                    "failed_case": tc
                }
                
            if not _outputs_match(out_str, tc["expected_output"]):
                return {
                    "all_passed": False,
                    "passed_count": passed_count,
                    "total_cases": len(test_cases),
                    "error": f"Wrong Output. Expected: {tc['expected_output'].strip()}, Got: {out_str}",
                    "failed_case": tc
                }
            passed_count += 1
            
        return {
            "all_passed": True,
            "passed_count": passed_count,
            "total_cases": len(test_cases),
            "error": None,
            "failed_case": None
        }
            
    except Exception as e:
        return {
            "all_passed": False,
            "passed_count": 0,
            "total_cases": len(test_cases),
            "error": f"Sandbox Exception: {str(e)}",
            "failed_case": None
        }
    finally:
        # Prevent ghost containers
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

async def run_adversarial_generator(generator_code: str, timeout_seconds: int = 5) -> dict:
    default_result = {"edge_cases": [], "stress_inputs": []}
    image = "python:3.10-slim"
    filename = "generator.py"
    container = None
    try:
        d_client = _get_client()
        try:
            d_client.images.get(image)
        except docker.errors.ImageNotFound:
            d_client.images.pull(image)

        tmpfs = {"/tmp": "rw,noexec,nosuid,size=64m"}
        create_kwargs = {
            "image": image,
            "command": "sleep infinity",
            "network_disabled": True,
            "mem_limit": "128m",
            "read_only": True,
            "tmpfs": tmpfs,
            "user": "1000:1000",
            "detach": True
        }
        try:
            container = d_client.containers.create(**create_kwargs)
        except Exception:
            create_kwargs.pop("user", None)
            container = d_client.containers.create(**create_kwargs)
            
        container.start()
        container.put_archive("/tmp", create_tar_archive(filename, generator_code))
        
        exec_cmd = ["timeout", f"{timeout_seconds}s", "python3", f"/tmp/{filename}"]
        exit_code, output = await asyncio.to_thread(container.exec_run, exec_cmd)
        out_str = output.decode('utf-8', errors='replace').strip()
        
        if exit_code != 0 or not out_str:
            return default_result
            
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
                
        valid_stress_inputs = [str(s) for s in stress_inputs if s is not None]
        return {
            "edge_cases": valid_edge_cases,
            "stress_inputs": valid_stress_inputs
        }
    except Exception:
        return default_result
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

async def execute_stress_probe(language: str, code: str, stress_inputs: list[str], timeout_seconds: int = 5) -> dict:
    image = "python:3.10-slim" if language == "python" else "gcc:12"
    filename = "solution.py" if language == "python" else "solution.cpp"
    
    tmpfs = {"/tmp": "rw,noexec,nosuid,size=64m"}
    if language == "cpp":
        tmpfs = {"/tmp": "rw,nosuid,size=64m"}
        
    container = None
    try:
        d_client = _get_client()
        try:
            d_client.images.get(image)
        except docker.errors.ImageNotFound:
            d_client.images.pull(image)
            
        create_kwargs = {
            "image": image,
            "command": "sleep infinity",
            "network_disabled": True,
            "mem_limit": "128m",
            "read_only": True,
            "tmpfs": tmpfs,
            "user": "1000:1000",
            "detach": True
        }
        try:
            container = d_client.containers.create(**create_kwargs)
        except Exception:
            create_kwargs.pop("user", None)
            container = d_client.containers.create(**create_kwargs)
            
        container.start()
        container.put_archive("/tmp", create_tar_archive(filename, code))
        
        if language == "cpp":
            compile_cmd = ["g++", "-O2", f"/tmp/{filename}", "-o", "/tmp/solution"]
            exit_code, output = await asyncio.to_thread(container.exec_run, compile_cmd)
            if exit_code != 0:
                return {
                    "survived": False,
                    "error": f"Compilation Error:\n{output.decode('utf-8', errors='replace')}",
                    "is_timeout": False,
                    "failed_stress_index": None
                }
                
        run_cmd = ["python3", f"/tmp/{filename}"] if language == "python" else ["/tmp/solution"]
        
        for i, s_input in enumerate(stress_inputs):
            input_file = f"stress_input_{i}.txt"
            container.put_archive("/tmp", create_tar_archive(input_file, s_input))
            
            exec_run_cmd = ["timeout", f"{timeout_seconds}s", "sh", "-c", f"{run_cmd[0]} {run_cmd[1] if len(run_cmd)>1 else ''} < /tmp/{input_file}"]
            exit_code, output = await asyncio.to_thread(container.exec_run, exec_run_cmd)
            out_str = output.decode('utf-8', errors='replace').strip()
            
            if exit_code == 124:
                return {
                    "survived": False,
                    "error": f"Time Limit Exceeded (Code 124, >{timeout_seconds}s) on stress input {i}",
                    "is_timeout": True,
                    "failed_stress_index": i
                }
            if exit_code != 0:
                return {
                    "survived": False,
                    "error": f"Runtime Error (Code {exit_code}) on stress input {i}:\n{out_str}",
                    "is_timeout": False,
                    "failed_stress_index": i
                }
            if not out_str:
                return {
                    "survived": False,
                    "error": f"Empty Output on stress input {i}",
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
            "error": f"Sandbox Exception during stress probe: {str(e)}",
            "is_timeout": False,
            "failed_stress_index": None
        }
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass
