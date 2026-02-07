"""Code execution handler with dangerous pattern guard."""
import io
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr

import hou

DANGEROUS_PATTERNS = [
    "hou.exit", "os.remove", "os.unlink", "shutil.rmtree",
    "subprocess", "os.system", "os.popen", "__import__",
]


def execute_code(code, allow_dangerous=False):
    """Executes arbitrary Python code within Houdini."""
    if not allow_dangerous:
        for pattern in DANGEROUS_PATTERNS:
            if pattern in code:
                raise ValueError(
                    f"Dangerous pattern detected: '{pattern}'. "
                    "Pass allow_dangerous=True to override."
                )
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    try:
        namespace = {"hou": hou}
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, namespace)

        return {
            "executed": True,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue()
        }
    except Exception as e:
        print("--- Houdini MCP: execute_code Error ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("--- End Error ---", file=sys.stderr)
        raise Exception(f"Code execution error: {str(e)}")
