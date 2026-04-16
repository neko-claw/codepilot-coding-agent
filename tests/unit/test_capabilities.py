from codepilot.tools.capabilities import default_capability_set


def test_capability_metadata_marks_code_interpreter_as_sandboxed() -> None:
    capability_map = {capability.name: capability for capability in default_capability_set()}

    interpreter = capability_map["code_interpreter"]
    assert interpreter.requires_isolation is True
    assert "Python" in interpreter.description


def test_capability_metadata_marks_file_tools_as_non_isolated() -> None:
    capability_map = {capability.name: capability for capability in default_capability_set()}

    assert capability_map["read_file"].requires_isolation is False
    assert capability_map["write_file"].requires_isolation is False
    assert capability_map["edit_file"].requires_isolation is False
