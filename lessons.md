# Project Lessons

Project-specific corrections for Robot Workflow.

## 2026-10-03: Report layout must fit registered components

- Context: The user found the ten-repository report confusing.
- Mistake: A fixed 1040 × 520 canvas clipped nodes at y=544; showing every dependency and long artifact lists obscured the main flow.
- Rule: Compute canvas bounds from displayed nodes and route margins. Group domain examples into readable lanes, show focused connections by default, and put impact paths before collapsible source details. Check the rendered report at desktop and narrow widths before delivery.
