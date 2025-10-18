---
description: Analyze staged changes and suggest a conventional commit message
---

Analyze the currently-staged git changes and suggest a conventional commit message.

Follow these steps:

1. Run `git diff --staged` to see the staged changes
2. Run `git status` to see which files are staged
3. Run `git log --oneline -10` to see recent commit message patterns in this repository
4. Analyze the staged changes to determine:
   - **Type**: Choose the appropriate conventional commit type:
     - `feat`: New feature
     - `fix`: Bug fix
     - `docs`: Documentation changes
     - `style`: Code style/formatting (no functional changes)
     - `refactor`: Code refactoring (no functional changes)
     - `perf`: Performance improvements
     - `test`: Adding or updating tests
     - `chore`: Maintenance tasks, dependency updates, etc.
     - `ci`: CI/CD configuration changes
     - `build`: Build system or dependency changes
   - **Scope**: Identify what part of the codebase is affected (e.g., `api`, `ui`, `graphs`, `docker`, `workflow`, etc.). Scope should be concise and relevant. Omit if changes span multiple areas.
   - **Description**: Write a clear, concise description in imperative mood (e.g., "add feature" not "added feature")

5. Present the suggested commit message in this format:
   ```
   <type>(<scope>): <description>
   ```
   Or if no scope is appropriate:
   ```
   <type>: <description>
   ```

6. Include a brief explanation of why you chose this type and scope

7. Ask if the user would like to:
   - Use this message as-is
   - Modify it
   - See a longer commit message with a body

IMPORTANT: Only analyze staged changes. If nothing is staged, inform the user and suggest they stage changes first with `git add`.
