"""Unit tests for script secret scanner."""

from so_mcp.sync.secret_scanner import scan_script_for_secrets


def test_scan_clean_script() -> None:
    body = """
    #setLanguageLevel 3;
    Ticket t;
    t.load(123);
    print(t.getValue("title"));
    """
    warnings = scan_script_for_secrets(body)
    assert warnings == []


def test_scan_hardcoded_password() -> None:
    body = """
    String user = "admin";
    String password = "SecretPassword123!";
    print(user);
    """
    warnings = scan_script_for_secrets(body)
    assert len(warnings) == 1
    assert "Potential hardcoded password" in warnings[0]
    assert "line 3" in warnings[0]


def test_scan_bearer_token() -> None:
    body = """
    HTTP http;
    http.addHeader("Authorization", "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummypayload");
    """
    warnings = scan_script_for_secrets(body)
    assert len(warnings) == 1
    assert "Bearer token detected" in warnings[0]


def test_scan_commented_password_ignored() -> None:
    body = """
    // password = "some_commented_password";
    /* pwd = "another_comment"; */
    print("hello");
    """
    warnings = scan_script_for_secrets(body)
    assert warnings == []
