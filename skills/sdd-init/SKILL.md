---
name: sdd-init
description: >
  SDD step 0. Analyse the project codebase and create docs/project.md with
  tech stack, architecture, and conventions. Run once before starting SDD in a new project.
  If docs/project.md already exists, asks whether to regenerate it.
---

# SDD: Init docs/project.md

You are a senior software architect analysing a project to produce its context document.

## Pre-conditions

Check whether `docs/project.md` already exists.

**If it exists:**
Ask the user:
> "`docs/project.md` already exists. Do you want to regenerate it? This will overwrite the current file."

Wait for confirmation. If the user says no, stop and tell them to edit the file manually.
If the user confirms, proceed with the full process below.

**If it does not exist:**
Proceed immediately.

---

## Process

### 1. Detect the Tech Stack

Scan the project root and source tree for build and configuration files to auto-detect as much as possible:

| What to find       | Where to look                                                                                                                                                                                  |
|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Language & version | `pom.xml` (`<java.version>`), `build.gradle`/`build.gradle.kts` (`jvmToolchain`, `sourceCompatibility`), `.java-version`, `pyproject.toml`, `package.json` (`engines`), `go.mod`, `Cargo.toml` |
| Framework          | `pom.xml` / `build.gradle` dependencies — Spring Boot, Quarkus, Micronaut, FastAPI, Express, Django, Rails, etc.                                                                               |
| Build tool         | Presence of `pom.xml` (Maven), `gradlew` (Gradle), `package.json` (npm/yarn/pnpm), `Makefile`, `pyproject.toml` (Poetry/Hatch)                                                                 |
| Database           | Dependencies or config files — `spring.datasource` in `application.properties`/`application.yml`, `DATABASE_URL` in `.env.example`, docker-compose services                                    |
| ORM / data access  | Dependencies — Hibernate/JPA, Spring Data, SQLAlchemy, Prisma, TypeORM, GORM, Diesel                                                                                                           |
| Migrations         | Dependencies or directories — Flyway, Liquibase, Alembic, `db/migrate/` (Rails), Prisma migrate                                                                                                |
| Messaging          | Dependencies or docker-compose services — Kafka, RabbitMQ, SQS, Redis Streams                                                                                                                  |
| Testing libraries  | Test-scope dependencies — JUnit 5, Mockito, Testcontainers, RestAssured, pytest, Jest, Vitest, RSpec                                                                                           |
| Other libraries    | Remaining notable dependencies — Spring Security, MapStruct, Lombok, Resilience4j, OpenAPI, etc.                                                                                               |

Read `docker-compose.yml` or `docker-compose.yaml` if present — it often reveals the database, messaging, and cache stack.

### 2. Detect Architecture & Conventions

Explore the source tree structure:

- Identify the top-level source layout (e.g., `src/main/java`, `src/`, `app/`, `lib/`)
- Infer the architecture pattern from package/directory names:
  - Packages named `controller`, `service`, `repository` → Layered
  - Packages named `domain`, `application`, `infrastructure`, `adapter` → Hexagonal / Clean
  - Packages named after business modules (e.g., `order`, `payment`, `user`) each containing layers → Modular Monolith
  - Multiple top-level services each with their own build file → Microservices
- Identify the base package name (e.g., `com.example.myapp`)
- Look for a centralised error handler (e.g., `GlobalExceptionHandler`, middleware, error boundary, or equivalent)
- Look for a base REST path prefix in controllers or config (e.g., `/api/v1`)
- Note any security config (e.g., `SecurityConfig`, auth annotations, JWT setup)

### 3. Ask Clarifying Questions

Some information cannot be reliably detected. Ask the user the following questions in a single grouped message — do not ask them one at a time:

```
I've analysed the project. Before I write docs/project.md, I need a few details:

1. **Project name and mission:** What does this application do, and who uses it?
   (1-2 sentences is enough — this is the "why we exist" paragraph.)

2. **Architecture pattern:** Based on the source layout, I think this uses [detected pattern].
   Is that right, or would you describe it differently?

3. **Key conventions:** Are there any conventions AI Agent should follow that aren't obvious from the code?
   For example: naming rules, auth requirements per endpoint, error response format, pagination style.

4. **Approved dependencies:** Are there any constraints on what libraries can be added?
   (If not, I'll list the detected dependencies as approved by default.)
```

Adjust or omit questions 2–4 if you already have high confidence from the codebase scan.

Wait for the user's answers before writing the file.

### 4. Write docs/project.md

Create `docs/` if it does not exist. Write `docs/project.md` with this structure, filled in from your analysis and the user's answers:

```markdown
# Project: <Name>

## Mission
<One paragraph on what this application does and who it serves.>

## Tech Stack
- Language: <language and version>
- Framework: <framework and version>
- Build tool: <tool>
- Database: <database and version if known>
- ORM: <ORM / data access library>
- Migrations: <migration tool, or "none">
- Messaging: <messaging system, or "none">
- Testing: <testing libraries>
- Other: <other notable libraries>

## Architecture
<Describe the pattern: Layered / Hexagonal / DDD / Modular Monolith / Microservices>
<Describe the package structure with an example, e.g.:>
<  com.example.<module>.<layer>  →  com.example.user.controller, com.example.user.service>

## Conventions
- Package naming: <convention>
- REST base path: <base path, e.g. /api/v1>
- Error handling: <mechanism, e.g. centralised exception handler, error middleware, global error boundary>
- Authentication: <default auth requirement, e.g. all endpoints require auth unless annotated @Public>
- <Any other conventions the user provided>

## Approved Dependencies
<Bulleted list of libraries approved for use. Anything outside this list requires a flag before adding.>
```

Do not leave any placeholder text (angle-bracket tokens) in the output — fill every field or omit the line if genuinely unknown.

### 5. Confirm

After writing the file:
- Show the user a summary of what was detected automatically vs. what they provided
- Tell them to review `docs/project.md` and update anything that looks wrong
- Remind them to keep this file up to date as the stack evolves — it is the primary input for all other SDD skills
- Prompt them to run `/sdd-feature <feature description>` to start their first feature
