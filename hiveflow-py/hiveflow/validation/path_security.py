"""Path security validation for document inputs.

Validates that file paths resolve within allowed directories and rejects
directory traversal attacks and out-of-scope symlinks.
"""

from pathlib import Path


def validate_document_path(
    path: str,
    working_dir: Path,
    allowed_paths: list[Path] | None = None,
) -> Path:
    """Validate and resolve a document path securely.

    Resolves the path relative to working_dir, then checks that the resolved
    absolute path falls within the working directory or one of the explicitly
    allowed paths. Rejects traversal sequences and symlinks that escape scope.

    Args:
        path: Raw path string from user input.
        working_dir: The working directory to resolve relative paths against.
        allowed_paths: Optional additional directories that are allowed.

    Returns:
        Resolved absolute Path.

    Raises:
        ValueError: If the path contains traversal sequences or resolves
            outside allowed directories.
        FileNotFoundError: If the resolved path does not exist.
    """
    raw = Path(path)

    # Reject explicit traversal sequences in the raw input
    parts = raw.parts
    if ".." in parts:
        raise ValueError(f"Document path '{path}' contains directory traversal sequences")

    # Resolve relative to working_dir
    resolved = raw.resolve() if raw.is_absolute() else (working_dir / raw).resolve()

    # Build the list of allowed root directories
    allowed_roots = [working_dir.resolve()]
    if allowed_paths:
        allowed_roots.extend(p.resolve() for p in allowed_paths)

    # Check that the resolved path falls within an allowed root
    inside_allowed = False
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            inside_allowed = True
            break
        except ValueError:
            continue

    if not inside_allowed:
        raise ValueError(f"Document path '{path}' is outside allowed directories")

    # Check existence
    if not resolved.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    # Check that the file is actually a file (not a directory)
    if not resolved.is_file():
        raise ValueError(f"Document path '{path}' is not a file")

    return resolved
