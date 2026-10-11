# Architecture

## Separation of responsibilities

### Scanner
Answers: **What should be considered?**

### Optimizer
Answers: **What should the portfolio own and at what target weights?**

### Execution engine
Answers: **What trades are required, are they permitted, and how should they be routed?**

## Phase 1 data contract

Optimizer-compatible target input:

```json
{
  "portfolio_date": "2026-11-02",
  "targets": {
    "SPY": 0.18,
    "QQQ": 0.40,
    "GLD": 0.34,
    "SCHD": 0.08
  }
}
```

The execution engine should eventually validate a versioned schema rather than import optimizer internals. This keeps repositories independently testable and allows an optimizer version to be frozen while the execution engine continues evolving.

## Core invariant

A proposed order must never reach a broker adapter before passing pre-trade risk checks.
