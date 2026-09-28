name: Bug report
description: Something broke or behaved unexpectedly
labels: ["bug"]
body:
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: Also tell us what you expected to happen.
      placeholder: |
        I ran X, expected Y, but got Z.
    validations:
      required: true
  - type: dropdown
    id: pipeline
    attributes:
      label: Which pipeline?
      options:
        - Traditional
        - Hybrid (Jev)
        - Compare mode
        - Benchmark Lab
        - Setup / install
        - Other / not sure
    validations:
      required: true
  - type: textarea
    id: trace
    attributes:
      label: Trace / error output
      description: Copy the trace panel output (it shows every Jev decision) or the backend error. Redact any keys.
      render: shell
  - type: textarea
    id: environment
    attributes:
      label: Environment
      description: OS, Python version, bun version, and backend `/health` status (curl http://localhost:8000/health).
      placeholder: "Ubuntu 24.04, Python 3.12.7, bun 1.x, health: ok"
  - type: checkboxes
    id: checks
    attributes:
      label: Preflight
      options:
        - label: I checked the [setup guide's troubleshooting table](https://github.com/kanishka-namdeo/jev-rag/blob/main/docs/setup.md#troubleshooting) first
          required: true
        - label: No API keys or secrets appear in what I pasted
          required: true
