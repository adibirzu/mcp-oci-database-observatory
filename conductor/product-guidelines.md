# Product Guidelines

## Communication Style & Prose
The DB AI Agent should communicate using a blend of professional precision and helpful guidance.
- **Tone**: Maintain a professional and technical tone that respects the expertise of DBAs and SREs while remaining approachable and conversational when explaining complex scenarios.
- **Directness**: Responses should be action-oriented and focused on results, providing clear status updates and commands with minimal unnecessary preamble.
- **Clarity**: Use precise technical terminology but provide context or explanations when guiding users through troubleshooting steps.

## Visual Identity & Output Formats
- **Structured Output**: Prioritize JSON or well-formatted tables for data-heavy responses to facilitate automation and easy parsing by other tools.
- **Rich Interaction**: Use terminal formatting (colors, bold text) and relevant emojis to clearly distinguish between success, warnings, and critical errors in CLI environments.
- **Standardized Logging**: All system logs must adhere to standard levels (INFO, WARN, ERROR) and include consistent timestamps and correlation IDs for distributed tracing.

## Error Handling & Failure Communication
- **Transparency**: When failures occur, provide detailed error messages and potential root causes. Technical stack traces should be available for debugging.
- **Actionability**: Error messages must not just state the problem but also suggest specific remediation steps or commands the user can execute to resolve the issue.

## Brand Messaging Principles
- **Reliability**: Every interaction should reinforce the system's stability and the accuracy of its database operations.
- **Intelligence**: Highlight the agent's capability to orchestrate complex tasks and reason through database performance issues autonomously.
- **Efficiency**: Emphasize how the system streamlines observability and saves time through intelligent automation.

## Design Principles
- **API-First**: All core functionality must be exposed through robust, well-documented APIs before being surfaced in the UI or CLI.
- **Observability-Native**: Tracing, metrics, and structured logging are first-class citizens and must be integrated into every new feature from inception.
- **Security-by-Design**: Security, including RBAC and secret management, is never an afterthought and must be baked into the architectural design of every component.
