name: Feature request
description: Propose an improvement or a new benchmark scenario
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: What failure mode or gap does this address?
      description: Features here usually fix a measured weakness — the more concrete, the better.
      placeholder: |
        On corpora with X, the hybrid currently over-abstains / mis-routes /
        loses to traditional because Y.
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: What would you like to see?
      description: Sketch the behavior, UI, or scenario. Benchmark scenario ideas (near-duplicates, multilingual, abstention traps) are especially valued.
    validations:
      required: true
  - type: textarea
    id: evidence
    attributes:
      label: Evidence (optional)
      description: Any run numbers, trace screenshots, or references that motivate it.
  - type: checkboxes
    id: scope
    attributes:
      label: Scope check
      options:
        - label: It keeps the project local-first (cloud only for the OpenAI-compatible generator endpoint)
          required: true
