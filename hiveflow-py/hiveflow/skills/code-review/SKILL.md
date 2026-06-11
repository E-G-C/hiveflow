---
name: code-review
description: >
  Perform systematic code reviews on source code files or diffs. Evaluates code
  quality, correctness, security, performance, and maintainability. Use when
  reviewing pull requests, code changes, or assessing code quality.
metadata:
  author: hiveflow
  version: "1.0"
---

# Code Review

## When to use this skill

Activate this skill when you need to review code changes, evaluate code quality,
or provide feedback on pull requests or source code files.

## Review process

1. **Understand context**: Read the code or diff carefully. Identify the purpose
   of the changes and the surrounding code architecture.

2. **Check correctness**: Verify logic, edge cases, error handling, and that the
   code does what it claims to do. Look for off-by-one errors, null/undefined
   references, resource leaks, and incorrect assumptions.

3. **Evaluate security**: Look for injection vulnerabilities (SQL, command,
   XSS), authentication and authorization gaps, data exposure, insecure
   defaults, and unsafe deserialization or file operations.

4. **Assess performance**: Identify unnecessary allocations, O(n^2) patterns in
   hot paths, missing caching opportunities, unneeded network round-trips, and
   resource leaks (connections, file handles, memory).

5. **Review maintainability**: Check naming clarity, function decomposition,
   documentation quality, adherence to project conventions, and whether the
   change is appropriately scoped (not doing too much or too little).

6. **Check test coverage**: Assess whether tests exist and cover the critical
   paths, edge cases, and error conditions introduced by the change.

## Output format

Structure your review as:

- **Summary**: One-paragraph overall assessment of the change.
- **Critical Issues**: Must-fix problems (bugs, security vulnerabilities, data
  loss risks). Each with file path, line reference, and suggested fix.
- **Suggestions**: Improvements for quality and maintainability that are not
  blocking. Each with rationale.
- **Positive Notes**: What was done well — acknowledge good patterns, thorough
  tests, or clear documentation.
- **Verdict**: One of APPROVED, CHANGES_REQUESTED, or NEEDS_DISCUSSION, with a
  brief justification.
