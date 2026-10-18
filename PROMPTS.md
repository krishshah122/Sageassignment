# Prompt log

Append-only record of user prompts, pasted line by line as given.

## Prompt 1

I have an assignment to build a complete software system. Your first task is to understand the requirements, not to implement anything.

Read the assignment carefully and produce:

1. Functional requirements: every feature the system must support.
2. Non-functional requirements: performance, security, reliability, scalability, and maintainability.
3. User roles and their permissions.
4. Main user workflows, from start to finish.
5. Data entities, relationships, and important constraints.
6. API endpoints and expected request/response contracts.
7. External services, integrations, and configuration requirements.
8. Edge cases, failure scenarios, and validation rules.
9. Acceptance criteria that can be verified through tests.
10. Ambiguities or missing information that need clarification.

Classify requirements as:
- Must-have for the assignment
- Important but secondary
- Optional improvements

Do not invent requirements. Mark assumptions explicitly and ask me about decisions that materially affect the architecture.

Do not write code, install packages, or modify files yet.

At the end, provide a traceability table mapping every requirement to the component that will implement it and the test that will verify it. also make a file prompt list and paste all my given proomt these which wver i npu lin eby line also make a skilsl.md tor your udnesrtabd

## Prompt 2

Using the approved requirements, propose a maintainable architecture for this system.

Explain:

1. The major components and their responsibilities.
2. The data flow between components.
3. The database schema and relationships.
4. API contracts between frontend and backend.
5. Authentication and authorization boundaries.
6. External service integrations and failure handling.
7. Configuration and secrets management.
8. Testing strategy.
9. Deployment architecture.
10. Important trade-offs and why this design is appropriate for the assignment.

Keep the design as simple as possible while satisfying the requirements. Do not introduce microservices, queues, caching layers, abstractions, or dependencies unless there is a clear need.

Define explicit module boundaries. Each component should have a clear responsibility and communicate through documented interfaces.

Identify which decisions are reversible and which would be expensive to change later.

Do not modify the repository yet. Present the architecture, proposed directory structure, data model, API contracts, and implementation sequence for review.  alod ad dthe above order requrment in my project file as proj.mf or txt

## Prompt 3

Build
