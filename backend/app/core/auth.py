from fastapi import Request

# Deterministic identifier for single-user desktop ownership scope
DEFAULT_OWNER_ID: str = "default_user"


async def get_current_owner_id(request: Request = None) -> str:
    """
    Dependency that resolves the verified ownership scope for memory operations.

    In the current single-user Windows 11 desktop application, this deterministically
    returns DEFAULT_OWNER_ID ("default_user").

    Security note:
    - Client-controlled HTTP headers (e.g. X-Foja-Owner-Id) are NEVER trusted or inspected.
    - Automated tests simulate different owners by using FastAPI's dependency_overrides.
    - In future multi-user phases, this dependency will extract the verified identity
      from cryptographically validated tokens (e.g., JWT claims / session cookies).
    """
    return DEFAULT_OWNER_ID
