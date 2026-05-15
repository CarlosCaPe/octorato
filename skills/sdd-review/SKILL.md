---
name: sdd-review
description: >
  SDD step 5. Reviews the implemented feature code against language and
  framework best practices, checks for code duplication, security vulnerabilities,
  performance issues, test coverage, and alignment with feature.md acceptance criteria.
  Use after /sdd-implement or on any existing feature implementation.
argument-hint: <file, package, or module path to review (optional, defaults to full diff)>
---

# SDD: Code Review

You are a principal engineer conducting a thorough code review.
Your review must be honest, specific, and actionable — not generic.
Every finding must reference the exact file and line range.

## Inputs

| Input         | Required | Description                                                               | Example                           |
|---------------|----------|---------------------------------------------------------------------------|-----------------------------------|
| `review_path` | Optional | File, package, or module path to review. Defaults to full git diff scope. | `src/auth/` |

## Steps

### Step 0: Validate Inputs (ALWAYS DO THIS FIRST)

- If `review_path` is provided → scope the review to that path only. Proceed to Step 1.
- If `review_path` is missing → determine scope automatically:
  1. Run `git diff main...HEAD --name-only` to find files changed in this branch.
  2. If not on a feature branch, ask the user to specify a path or confirm they want a full codebase review.
  Proceed to Step 1 once scope is resolved.

---

## Pre-conditions
Read the following before starting:
- `docs/project.md` — tech stack, architecture, conventions
- `feature.md` — acceptance criteria and functional requirements (if present)
- `plan.md` — intended implementation approach (if present)

## Scope
Review the path or file set resolved in Step 0. Focus on changed/added files; note but do not deeply review unrelated pre-existing code.

---

## Review Dimensions

Work through each dimension below in order. For each finding, add one row to the appropriate severity table (see Output Format):

```
| [ ] | `path/to/File.java:line` | <category> | <one sentence: what is wrong and why it matters> | <one sentence: concrete fix> |
```

- First column `[ ]` is the status checkbox — change to `[x]` once the finding is resolved.
- Keep **Problem** and **Suggestion** to a single sentence; no code blocks inside table cells.

Severity levels:
- 🔴 **CRITICAL** — Must fix before merging (security holes, data loss risk, broken ACs)
- 🟠 **MAJOR** — Should fix before merging (significant bugs, serious design flaws)
- 🟡 **MINOR** — Fix soon but not a blocker (code smell, minor inefficiency)
- 🔵 **INFO** — Suggestion or best practice (style, optional improvement)

---

### Dimension 1: Acceptance Criteria Verification
If `feature.md` is present, go through every AC:
- Confirm there is a test that directly covers it
- Confirm the implementation actually satisfies it (not just that a test exists)
- Flag any AC with no test coverage as 🔴 CRITICAL
- **For each AC that is fully covered and satisfied, mark it as complete in `feature.md`** by changing `- [ ]` to `- [x]` on that AC's line

---

### Dimension 2: Language & Framework Best Practices

Review against the conventions and idiomatic patterns for the tech stack declared in `docs/project.md`. 
Consult any linting rules, style guides, or formatter config present in the project.

#### Language
- Code is idiomatic for the language in use — modern language features used appropriately
- No antipatterns common to this language (resource leaks, unsafe type coercions, ignored errors, etc.)
- Error handling follows the project's declared convention (exceptions, error return values, Result types, etc.)
- No debug output left in production code (`print`, `console.log`, etc.) — structured logging only
- Immutability or value semantics preferred where the language supports it

#### Framework
- Follows the framework's recommended layer responsibilities — no business logic in the presentation/controller layer
- Configuration is centralised per the framework's conventions — no scattered inline config values
- Dependency injection or service wiring uses the framework's standard mechanism
- HTTP status codes are semantically correct for the outcome
- Error/exception handling is centralised (middleware, handler, filter) not duplicated per endpoint
- Tests use the narrowest test scope available — prefer unit or slice tests over full-stack tests where sufficient

#### Data Access
- No unbounded queries on potentially large datasets — pagination applied where appropriate
- N+1 query risks identified and addressed (eager loading, batching, or explicit joins)
- Queries use the framework's safe parameterisation mechanism — no string concatenation in queries
- Absence of a record is handled explicitly before use (null check, empty-optional guard, etc.)

---

### Dimension 3: Security

- **Injection**: No string concatenation in queries (SQL, NoSQL, etc.) — parameterised queries only
- **Authentication & Authorisation**: Sensitive endpoints are protected; no security decisions based solely on client-supplied data without server-side validation
- **Input Validation**: All request bodies and parameters are validated before use
- **Sensitive Data Exposure**: No passwords, tokens, PII, or secrets logged or returned in API responses
- **Mass Assignment**: Request input is not bound directly to persistent models without explicit field filtering
- **Dependency Risk**: Flag any new dependency not in `docs/project.md` approved stack
- **CORS / CSRF**: If new endpoints are added, confirm CORS config is not overly permissive
- **Error Messages**: Stack traces or internal details not leaked in error responses

---

### Dimension 4: Code Duplication

- Scan changed files for logic that duplicates existing utilities, services, or helpers in the codebase
- Flag copy-paste between new test classes or between service methods
- Identify repeated `if/else` or `switch` blocks that should be polymorphism or a strategy pattern
- Note any hardcoded values that appear in multiple places and should be constants or config

---

### Dimension 5: Design & Architecture

- Code respects the layering in `docs/project.md` (e.g., no domain logic leaking into controllers,
  no data-access or infrastructure code in the domain layer for Hexagonal/Clean Architecture)
- Classes follow Single Responsibility — flag classes that do too many things
- No inappropriate `static` methods carrying state
- Proper use of interfaces and abstractions — not over-engineered, but not skipping meaningful abstractions either
- Package structure consistent with existing conventions

---

### Dimension 6: Performance

- No synchronous blocking calls inside reactive/async pipelines (if applicable)
- No repeated database calls inside a loop — batch where possible
- Expensive operations (e.g., external API calls, file I/O) are not in hot paths without caching consideration
- Indexes implied by query patterns — flag queries on non-indexed columns if identifiable

---

### Dimension 7: Test Quality

- Tests follow Arrange-Act-Assert structure
- Test names clearly describe the scenario (`should_returnError_when_emailAlreadyExists`)
- No logic in tests (`if`, `for` loops) — each test is a single, clear scenario
- Mocks used only at architectural boundaries — no mocking of classes owned by the same module
- No arbitrary sleeps in tests — use proper async/polling utilities for asynchronous assertions
- Test data is minimal and focused — no bloated setup that obscures what's being tested
- Edge cases covered: null inputs, empty collections, boundary values

---

### Dimension 8: Observability

- New service methods and key business events have appropriate log statements at correct levels
  (`DEBUG` for diagnostic detail, `INFO` for business events, `WARN` for recoverable issues, `ERROR` for failures)
- No sensitive data in log messages
- If the project uses a metrics library, new significant operations are instrumented

---

## Output Format

Write the review to `review.md` in the project root using this structure:

```markdown
# Code Review: <Feature Name or Path>

## Summary
<2-3 sentence overall assessment. Be direct — is this ready to merge, needs minor fixes, or needs significant rework?>

## Findings

### 🔴 Critical

| Done | Location | Category | Problem | Suggestion |
|------|----------|----------|---------|------------|
| [ ] | `src/service/AuthService.java:42` | Null Safety | `user` may be null; NPE at runtime | Add null guard before line 42 |

### 🟠 Major

| Done | Location | Category | Problem | Suggestion |
|------|----------|----------|---------|------------|

### 🟡 Minor

| Done | Location | Category | Problem | Suggestion |
|------|----------|----------|---------|------------|

### 🔵 Info / Suggestions

| Done | Location | Category | Problem | Suggestion |
|------|----------|----------|---------|------------|

## Acceptance Criteria Coverage
| AC         | Test               | Status          |
|------------|--------------------|-----------------|
| AC-01: ... | `FooTest#test_...` | ✅ Covered       |
| AC-02: ... | —                  | ❌ No test found |

## Verdict
- [ ] ✅ Ready to merge
- [ ] 🟡 Merge after minor fixes (no re-review needed)
- [ ] 🟠 Requires fixes and re-review
- [ ] 🔴 Do not merge — significant issues found
```

After writing the file, print a one-line confirmation: `review.md written.`
Then show the **Summary** and **Verdict** sections inline so the user gets immediate context without opening the file.

---

## After the Review

Ask the user:
> "Would you like me to fix any of these findings now? You can say 'fix all critical and major' or call out specific items."

If the user asks for fixes, address them and then re-run the relevant tests to confirm the fixes hold.
If all findings are resolved, prompt the user to run `/sdd-archive` if not already done.
