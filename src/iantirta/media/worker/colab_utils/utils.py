


def get_status_code(e: Exception) -> int | None:
    """Safely extracts status code from various exception types."""
    if hasattr(e, "response") and e.response is not None and hasattr(e.response, "status_code"):
        return e.response.status_code
    if hasattr(e, "status_code"):
        return e.status_code
    return None

    
def is_terminal_error(e: Exception) -> bool:
    """Checks if an exception indicates a lost session (404/401)."""
    code = get_status_code(e)
    if code in (404, 401):
        return True
    # Some exceptions from jupyter-kernel-client might wrap the real one or be different
    err_msg = str(e)
    return bool("404" in err_msg or "401" in err_msg)
