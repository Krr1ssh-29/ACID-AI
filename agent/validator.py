"""Patch safety policy validator and unified diff parser.

Enforces strict defense-in-depth security policies:
- Path allowlisting (only application code, tests, and dependency manifests)
- Rejection of path traversal (..), absolute paths, and repository escapes
- Strict prohibition of .github/ workflows, .git/ internals, and secrets/credentials
- Size boundaries: maximum 5 files, maximum 150 modified lines
- Prohibition of binary diffs and file deletions
- In-memory verification against repository state (without modifying working tree)
"""
import os
import re
from typing import List, Optional, Tuple, Dict
from agent.models import (
    FilePatch,
    PatchValidationError,
    PatchValidationResult,
    AnalysisResult,
)

DEFAULT_MAX_CHANGED_FILES = 5
DEFAULT_MAX_MODIFIED_LINES = 150

ALLOWLISTED_PATH_PREFIXES = (
    "sample-app/",
    "src/",
    "tests/",
    "sample_app/",
    "app/",
    "lib/",
    "test/",
)

ALLOWLISTED_ROOT_MANIFESTS = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Dockerfile",
    "setup.py",
    "setup.cfg",
    "package.json",
)

DEPENDENCY_MANIFESTS = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "package.json",
)

SECRET_KEYWORD_PATTERNS = (
    "id_rsa",
    ".pem",
    ".key",
    "secret",
    "token",
    "credential",
    "password",
    ".env",
)


class MalformedDiffError(Exception):
    """Raised when unified diff syntax is invalid or corrupted."""
    pass


class BinaryPatchError(Exception):
    """Raised when unified diff contains binary file changes."""
    pass


def _normalize_diff_path(raw_path: str) -> str:
    """Normalize path from diff headers by stripping prefixes and timestamps."""
    cleaned = raw_path.strip()
    if "\t" in cleaned:
        cleaned = cleaned.split("\t")[0].strip()
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return cleaned.replace("\\", "/")


def parse_unified_diff(diff_text: str) -> List[FilePatch]:
    """Parse a unified diff text string into structured FilePatch objects.

    Args:
        diff_text: Raw unified diff string.

    Returns:
        List of FilePatch objects representing each affected file.

    Raises:
        MalformedDiffError: If diff headers or hunks are malformed.
        BinaryPatchError: If binary patch syntax is detected.
    """
    if not diff_text or not diff_text.strip():
        return []

    # Check for binary diff indicators
    if "Binary files " in diff_text or "GIT binary patch" in diff_text or "\x00" in diff_text:
        raise BinaryPatchError("Binary files diff detected; binary patches are strictly forbidden.")

    lines = diff_text.splitlines()
    file_patches: List[FilePatch] = []

    current_orig: Optional[str] = None
    current_target: Optional[str] = None
    current_lines: List[str] = []
    current_hunks = 0
    current_adds = 0
    current_dels = 0
    in_hunk = False

    def finalize_current_file():
        nonlocal current_orig, current_target, current_lines
        nonlocal current_hunks, current_adds, current_dels, in_hunk
        if current_orig is None and current_target is None:
            return

        if current_orig is None or current_target is None:
            raise MalformedDiffError(
                f"Incomplete diff header: orig={current_orig}, target={current_target}"
            )

        orig_clean = _normalize_diff_path(current_orig)
        target_clean = _normalize_diff_path(current_target)

        if orig_clean == "/dev/null" and target_clean == "/dev/null":
            raise MalformedDiffError("Diff specifies /dev/null for both source and target.")

        if orig_clean == "/dev/null":
            status = "added"
            norm_path = target_clean
        elif target_clean == "/dev/null":
            status = "deleted"
            norm_path = orig_clean
        else:
            status = "modified"
            norm_path = target_clean

        if current_hunks == 0:
            raise MalformedDiffError(f"No valid hunks found for file '{norm_path}'.")

        patch = FilePatch(
            path=norm_path,
            original_path=orig_clean,
            target_path=target_clean,
            additions=current_adds,
            deletions=current_dels,
            hunks_count=current_hunks,
            diff_content="\n".join(current_lines),
            status=status,
        )
        file_patches.append(patch)

        current_orig = None
        current_target = None
        current_lines = []
        current_hunks = 0
        current_adds = 0
        current_dels = 0
        in_hunk = False

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Ignore diff metadata command line (e.g. diff --git a/file b/file)
        if line.startswith("diff --git"):
            finalize_current_file()
            current_lines.append(line)
            i += 1
            continue

        if line.startswith("--- "):
            if current_orig is not None:
                # Started a new file without finishing prior
                finalize_current_file()
            current_orig = line[4:].strip()
            current_lines.append(line)
            i += 1
            # Next line must be +++
            if i < n and lines[i].startswith("+++ "):
                current_target = lines[i][4:].strip()
                current_lines.append(lines[i])
                i += 1
            else:
                raise MalformedDiffError(f"Malformed diff: expected '+++' following '---' at line {i + 1}.")
            continue

        if line.startswith("@@ "):
            if current_orig is None or current_target is None:
                raise MalformedDiffError(f"Hunk found before file headers at line {i + 1}.")
            # Validate hunk header pattern @@ -S[,C] +S[,C] @@
            hunk_match = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", line)
            if not hunk_match:
                raise MalformedDiffError(f"Invalid hunk header at line {i + 1}: '{line}'")
            current_hunks += 1
            in_hunk = True
            current_lines.append(line)
            i += 1
            continue

        if in_hunk:
            if line.startswith("+") and not line.startswith("+++"):
                current_adds += 1
                current_lines.append(line)
            elif line.startswith("-") and not line.startswith("---"):
                current_dels += 1
                current_lines.append(line)
            elif line.startswith(" "):
                current_lines.append(line)
            elif line.startswith("\\"):
                # E.g. \ No newline at end of file
                current_lines.append(line)
            elif not line.strip():
                # Some diff tools produce empty lines instead of ' '
                current_lines.append(" " + line)
            else:
                # Unexpected character inside hunk
                raise MalformedDiffError(
                    f"Invalid diff line inside hunk at line {i + 1}: '{line[:30]}...'"
                )
            i += 1
            continue

        # Metadata line outside hunks (e.g., index, new file mode, etc.)
        if current_orig is not None or current_target is not None:
            current_lines.append(line)
        i += 1

    finalize_current_file()
    return file_patches


def validate_file_path(path: str, repo_root: Optional[str] = None) -> List[PatchValidationError]:
    """Deterministically validate safety policies for a single file path.

    Args:
        path: File path string from the candidate patch.
        repo_root: Optional repository root path for canonical boundary checking.

    Returns:
        List of PatchValidationError instances if policies are violated.
    """
    errors: List[PatchValidationError] = []

    # 1. Absolute path check
    if path.startswith("/") or path.startswith("\\") or re.match(r"^[A-Za-z]:[\\/]", path):
        errors.append(
            PatchValidationError(
                code="ABSOLUTE_PATH_FORBIDDEN",
                message=f"Absolute path '{path}' is strictly forbidden.",
                file_path=path,
            )
        )
        return errors

    # 2. Path traversal sequence check
    parts = re.split(r"[\\/]", path)
    if ".." in parts:
        errors.append(
            PatchValidationError(
                code="PATH_TRAVERSAL_DETECTED",
                message=f"Directory traversal sequence '..' detected in '{path}'.",
                file_path=path,
            )
        )
        return errors

    norm_path = path.replace("\\", "/").strip().lstrip("/")

    # 3. Canonical path boundary resolution if repo_root is provided
    if repo_root:
        canonical_root = os.path.realpath(repo_root)
        canonical_target = os.path.realpath(os.path.join(repo_root, norm_path))
        try:
            rel = os.path.relpath(canonical_target, canonical_root)
            if rel.startswith("..") or os.path.isabs(rel) or canonical_target == canonical_root:
                errors.append(
                    PatchValidationError(
                        code="PATH_TRAVERSAL_DETECTED",
                        message=f"Target path '{path}' escapes repository boundary.",
                        file_path=path,
                    )
                )
                return errors
        except ValueError:
            # Different drive letters on Windows
            errors.append(
                PatchValidationError(
                    code="PATH_TRAVERSAL_DETECTED",
                    message=f"Target path '{path}' escapes repository drive boundary.",
                    file_path=path,
                )
            )
            return errors

    # 4. Prohibited target checks
    # A. .git internal repository metadata
    if norm_path == ".git" or norm_path.startswith(".git/") or "/.git/" in f"/{norm_path}/":
        errors.append(
            PatchValidationError(
                code="PROHIBITED_FILE_MODIFICATION",
                message=f"Modifying Git internals ('{path}') is strictly forbidden.",
                file_path=path,
            )
        )
        return errors

    # B. .github workflows and actions configurations
    if norm_path == ".github" or norm_path.startswith(".github/") or "/.github/" in f"/{norm_path}/":
        errors.append(
            PatchValidationError(
                code="PROHIBITED_FILE_MODIFICATION",
                message=f"Modifying GitHub workflows/actions ('{path}') is strictly forbidden.",
                file_path=path,
            )
        )
        return errors

    # C. Secrets, credentials, private keys, environment files
    base_name = os.path.basename(norm_path).lower()
    if base_name.startswith(".env") or any(keyword in base_name for keyword in SECRET_KEYWORD_PATTERNS):
        errors.append(
            PatchValidationError(
                code="PROHIBITED_FILE_MODIFICATION",
                message=f"Modifying sensitive, secret, or credential file ('{path}') is strictly forbidden.",
                file_path=path,
            )
        )
        return errors

    # D. Hidden files or directories (.bashrc, .ssh/, etc.)
    for part in parts:
        if part.startswith(".") and part not in (".", ".."):
            errors.append(
                PatchValidationError(
                    code="PROHIBITED_FILE_MODIFICATION",
                    message=f"Modifying hidden configuration file or directory ('{path}') is forbidden.",
                    file_path=path,
                )
            )
            return errors

    # 5. Allowlist check
    is_allowlisted = False
    for prefix in ALLOWLISTED_PATH_PREFIXES:
        if norm_path.startswith(prefix):
            is_allowlisted = True
            break

    if not is_allowlisted:
        if norm_path in ALLOWLISTED_ROOT_MANIFESTS:
            is_allowlisted = True

    if not is_allowlisted:
        errors.append(
            PatchValidationError(
                code="PATH_NOT_ALLOWLISTED",
                message=f"File '{path}' is not within approved application or test directories.",
                file_path=path,
            )
        )

    return errors


def _extract_hunks(diff_content: str) -> List[Tuple[int, int, List[str]]]:
    """Extract individual hunks as (orig_start, orig_count, hunk_lines) tuples."""
    hunks = []
    current_start = 0
    current_count = 0
    current_hunk_lines: List[str] = []
    in_hunk = False

    for line in diff_content.splitlines():
        if line.startswith("@@ "):
            if in_hunk:
                hunks.append((current_start, current_count, current_hunk_lines))
                current_hunk_lines = []
            m = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", line)
            if m:
                current_start = int(m.group(1))
                current_count = int(m.group(2)) if m.group(2) else 1
                in_hunk = True
            continue
        if in_hunk:
            current_hunk_lines.append(line)

    if in_hunk:
        hunks.append((current_start, current_count, current_hunk_lines))

    return hunks


def validate_repository_state(
    file_patches: List[FilePatch],
    repo_root: str,
) -> List[PatchValidationError]:
    """Verify in-memory that the patch matches the current repository state.

    CRITICAL: Does not write, modify, delete, or touch any disk files.

    Args:
        file_patches: Parsed list of FilePatch objects.
        repo_root: Root directory of the repository to check against.

    Returns:
        List of PatchValidationError instances if state mismatches are detected.
    """
    errors: List[PatchValidationError] = []

    for patch in file_patches:
        target_full_path = os.path.join(repo_root, patch.path)

        if patch.status == "added":
            if os.path.exists(target_full_path):
                errors.append(
                    PatchValidationError(
                        code="FILE_ALREADY_EXISTS",
                        message=f"Cannot create '{patch.path}': file already exists in repository.",
                        file_path=patch.path,
                    )
                )
            continue

        if patch.status == "modified":
            if not os.path.isfile(target_full_path):
                errors.append(
                    PatchValidationError(
                        code="TARGET_FILE_NOT_FOUND",
                        message=f"Target file '{patch.path}' does not exist in repository.",
                        file_path=patch.path,
                    )
                )
                continue

            try:
                with open(target_full_path, "r", encoding="utf-8", errors="replace") as f:
                    actual_lines = f.read().splitlines()
            except OSError as e:
                errors.append(
                    PatchValidationError(
                        code="TARGET_FILE_NOT_READABLE",
                        message=f"Could not read repository target file '{patch.path}': {e}",
                        file_path=patch.path,
                    )
                )
                continue

            hunks = _extract_hunks(patch.diff_content)
            for orig_start, orig_count, hunk_lines in hunks:
                # Extract expected original lines (lines starting with ' ' or '-')
                expected_lines = [
                    hl[1:] for hl in hunk_lines if hl.startswith((" ", "-"))
                ]
                if not expected_lines:
                    continue

                # Normal 1-indexed check
                start_idx = max(0, orig_start - 1)
                matched = False

                # Exact match at indicated line
                candidate = actual_lines[start_idx: start_idx + len(expected_lines)]
                if candidate == expected_lines:
                    matched = True
                else:
                    # Scan the file for the matching context lines
                    for idx in range(max(0, len(actual_lines) - len(expected_lines) + 1)):
                        if actual_lines[idx: idx + len(expected_lines)] == expected_lines:
                            matched = True
                            break

                if not matched:
                    errors.append(
                        PatchValidationError(
                            code="PATCH_STATE_MISMATCH",
                            message=(
                                f"Hunk at line {orig_start} in '{patch.path}' does not match "
                                "current repository file content."
                            ),
                            file_path=patch.path,
                        )
                    )

    return errors


def validate_patch(
    diff_text: str,
    repo_root: Optional[str] = None,
    max_files: int = DEFAULT_MAX_CHANGED_FILES,
    max_lines: int = DEFAULT_MAX_MODIFIED_LINES,
    diagnosis: Optional[AnalysisResult] = None,
) -> PatchValidationResult:
    """Enforce complete patch safety policies on candidate unified diff text.

    Args:
        diff_text: Raw candidate unified diff string.
        repo_root: Optional repository root for path boundary and state matching.
        max_files: Maximum allowed number of modified files (default: 5).
        max_lines: Maximum total modified lines allowed (default: 150).
        diagnosis: Optional validated AnalysisResult from Phase 03.

    Returns:
        PatchValidationResult containing boolean approval, error list, and warnings.
    """
    errors: List[PatchValidationError] = []
    warnings: List[str] = []

    # 1. Blank/Empty patch check
    if not diff_text or not diff_text.strip():
        errors.append(
            PatchValidationError(
                code="EMPTY_PATCH",
                message="Patch is empty or contains no valid diff content.",
            )
        )
        return PatchValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # 2. Unified diff parse check
    try:
        file_patches = parse_unified_diff(diff_text)
    except BinaryPatchError as e:
        errors.append(
            PatchValidationError(
                code="BINARY_PATCH_FORBIDDEN",
                message=str(e),
            )
        )
        return PatchValidationResult(is_valid=False, errors=errors, warnings=warnings)
    except MalformedDiffError as e:
        errors.append(
            PatchValidationError(
                code="MALFORMED_DIFF",
                message=f"Diff failed syntax validation: {e}",
            )
        )
        return PatchValidationResult(is_valid=False, errors=errors, warnings=warnings)

    if not file_patches:
        errors.append(
            PatchValidationError(
                code="EMPTY_PATCH",
                message="No modified files identified in patch.",
            )
        )
        return PatchValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # 3. Changed file count limit
    if len(file_patches) > max_files:
        errors.append(
            PatchValidationError(
                code="EXCESSIVE_FILES_CHANGED",
                message=f"Patch modifies {len(file_patches)} files; policy ceiling is {max_files}.",
            )
        )

    # 4. Total modified lines limit & operation checks
    total_modifications = sum(fp.additions + fp.deletions for fp in file_patches)
    if total_modifications > max_lines:
        errors.append(
            PatchValidationError(
                code="EXCESSIVE_LINES_MODIFIED",
                message=(
                    f"Patch modifies {total_modifications} lines (+/-); policy ceiling is {max_lines}."
                ),
            )
        )

    seen_paths: Dict[str, str] = {}
    for fp in file_patches:
        # A. Prohibit file deletions
        if fp.status == "deleted":
            errors.append(
                PatchValidationError(
                    code="FILE_DELETION_FORBIDDEN",
                    message=f"Deleting file '{fp.path}' is strictly prohibited by policy.",
                    file_path=fp.path,
                )
            )

        # B. Contradictory / duplicate file entries check
        if fp.path in seen_paths:
            if seen_paths[fp.path] != fp.status:
                errors.append(
                    PatchValidationError(
                        code="CONTRADICTORY_PATCH",
                        message=(
                            f"Contradictory operations specified for '{fp.path}': "
                            f"{seen_paths[fp.path]} vs {fp.status}."
                        ),
                        file_path=fp.path,
                    )
                )
        seen_paths[fp.path] = fp.status

        # C. Path safety checks
        path_errors = validate_file_path(fp.path, repo_root=repo_root)
        errors.extend(path_errors)

        # D. Dependency manifest warning check (Threat T-11)
        base = os.path.basename(fp.path).lower()
        if base in DEPENDENCY_MANIFESTS:
            warnings.append(
                f"Patch modifies dependency manifest '{fp.path}': "
                "manual human security review is strictly required before merging (Threat T-11)."
            )

    # 5. In-memory repository state check (if repo_root is provided and no prior path errors)
    if repo_root and not any(e.code in ("PATH_TRAVERSAL_DETECTED", "ABSOLUTE_PATH_FORBIDDEN") for e in errors):
        state_errors = validate_repository_state(file_patches, repo_root)
        errors.extend(state_errors)

    # 6. Diagnosis consistency check (optional contextual check)
    if diagnosis and not diagnosis.root_cause:
        warnings.append("Patch generated without grounded diagnosis root cause.")

    return PatchValidationResult(
        is_valid=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
    )
