import pytest

from execution.code_guard import UnsafeCodeError, guard_code


def test_allows_safe_pandas_code():
    guard_code("result = df['revenue'].sum()")


def test_allows_allowlisted_imports():
    guard_code("import numpy as np\nimport math\nresult = math.sqrt(np.array([4]).sum())")


@pytest.mark.parametrize("code", [
    "import os\nresult = os.listdir('.')",
    "import subprocess\nresult = subprocess.run(['ls'])",
    "import requests\nresult = requests.get('http://example.com')",
    "from socket import socket\nresult = 1",
])
def test_rejects_disallowed_imports(code):
    with pytest.raises(UnsafeCodeError):
        guard_code(code)


def test_rejects_dunder_attribute_access():
    with pytest.raises(UnsafeCodeError):
        guard_code("result = (1).__class__.__bases__[0]")


@pytest.mark.parametrize("code", [
    "result = eval('1+1')",
    "result = exec('x=1')",
    "result = open('/etc/passwd').read()",
    "result = __import__('os').getcwd()",
])
def test_rejects_dangerous_calls(code):
    with pytest.raises(UnsafeCodeError):
        guard_code(code)


def test_rejects_syntax_error():
    with pytest.raises(UnsafeCodeError):
        guard_code("result = (((")
