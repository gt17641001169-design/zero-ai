"""测试 <tool_call> 伪 XML 解析"""
import json
import tui_agent


def test_name_args_format():
    text = '<tool_call>local_monitor(check_ports="22,80,443")</tool_call>'
    calls = tui_agent._parse_tool_call_xml(text)
    assert len(calls) == 1, calls
    assert calls[0]["name"] == "local_monitor"
    args = json.loads(calls[0]["arguments"])
    assert args == {"check_ports": "22,80,443"}, args


def test_json_format():
    text = '<tool_call>{"name": "local_monitor", "arguments": {"check_ports": "22,80,443"}}</tool_call>'
    calls = tui_agent._parse_tool_call_xml(text)
    assert len(calls) == 1, calls
    assert calls[0]["name"] == "local_monitor"
    args = json.loads(calls[0]["arguments"])
    assert args == {"check_ports": "22,80,443"}, args


def test_multiple_calls():
    text = (
        '<tool_call>local_monitor(check_ports="22,80,443")</tool_call>'
        '一些说明文字'
        '<tool_call>system_info()</tool_call>'
    )
    calls = tui_agent._parse_tool_call_xml(text)
    assert len(calls) == 2, calls
    assert calls[0]["name"] == "local_monitor"
    assert calls[1]["name"] == "system_info"


def test_no_args():
    text = '<tool_call>system_info()</tool_call>'
    calls = tui_agent._parse_tool_call_xml(text)
    assert len(calls) == 1, calls
    assert calls[0]["name"] == "system_info"
    assert json.loads(calls[0]["arguments"]) == {}


if __name__ == "__main__":
    test_name_args_format()
    print("test_name_args_format passed")
    test_json_format()
    print("test_json_format passed")
    test_multiple_calls()
    print("test_multiple_calls passed")
    test_no_args()
    print("test_no_args passed")
    print("All tool_call XML parser tests passed!")
