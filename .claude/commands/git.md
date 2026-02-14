Run all tests, then commit and push.

## Steps

1. Run the full test suite using the uv virtual environment:
   ```
   uv run pytest
   ```
2. If any tests fail, stop and report the failures. Do NOT proceed to commit.
3. If all tests pass, create a git commit:
   - Stage all relevant changed files (be selective — avoid secrets or generated files)
   - Write a concise commit message summarizing the changes
4. Push the commit to the remote.
