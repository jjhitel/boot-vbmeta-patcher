from ltbox import constants

def test_tool_paths_exist():
    assert constants.ADB_EXE.name == "adb.exe"
    assert constants.FASTBOOT_EXE.name == "fastboot.exe"

def test_python_version_check():
    import sys
    assert sys.version_info.major == 3
