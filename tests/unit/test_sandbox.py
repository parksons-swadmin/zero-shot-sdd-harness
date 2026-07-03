import pandas as pd

from execution.sandbox import run_analysis_code


def test_happy_path_scalar_result():
    df = pd.DataFrame({"revenue": [10, 20, 30]})
    result = run_analysis_code("result = df['revenue'].sum()", {"df": df}, timeout_s=5)
    assert result["ok"] is True
    assert result["error"] is None
    assert result["result"]["type"] == "scalar"
    assert result["result"]["value"] == 60


def test_edge_case_dataframe_result_is_capped():
    df = pd.DataFrame({"x": list(range(500))})
    result = run_analysis_code("result = df", {"df": df}, timeout_s=5)
    assert result["ok"] is True
    assert result["result"]["type"] == "dataframe"
    assert result["result"]["total_rows"] == 500
    assert result["result"]["rows_returned"] <= 200
    assert result["result"]["truncated"] is True
    # never dumps the unbounded frame back as text
    assert len(result["result"]["data_json"]) <= 2000


def test_error_path_guard_rejects_unsafe_code():
    df = pd.DataFrame({"x": [1]})
    result = run_analysis_code("import os\nresult = os.listdir('.')", {"df": df}, timeout_s=5)
    assert result["ok"] is False
    assert "guard" in result["error"].lower()


def test_error_path_runtime_exception_is_captured():
    df = pd.DataFrame({"x": [1]})
    result = run_analysis_code("result = df['does_not_exist'].sum()", {"df": df}, timeout_s=5)
    assert result["ok"] is False
    assert result["error"]
    assert result["result"] is None


def test_error_path_timeout_is_enforced():
    df = pd.DataFrame({"x": [1]})
    code = "total = 0\nfor i in range(200_000_000):\n    total += i\nresult = total"
    result = run_analysis_code(code, {"df": df}, timeout_s=1)
    assert result["ok"] is False
    assert "timeout" in result["error"].lower()
