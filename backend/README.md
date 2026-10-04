# Backend

Planned stack: Python, FastAPI, Pydantic, and PostgreSQL.

This application will own request validation, application data, agent execution, benchmark execution, and evaluation. The agent runner will remain separate from HTTP handlers so a local command and, eventually, a worker can invoke the same logic.

Application PostgreSQL will store benchmark definitions and experiment results. Phoenix will receive execution telemetry. Results will reference their traces by ID.

No backend application has been initialized yet. Add modules as their phases arrive; start with explicit functions and introduce workers only when execution requirements justify them.
