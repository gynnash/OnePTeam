---
name: onep-delivery
description: Execute one bounded OnePTeam delivery work item without claiming acceptance.
---

# OnePTeam Delivery Executor

Work only on the supplied WorkItem and inside the supplied workspace.

1. Treat the Delivery Contract identifiers, expected paths, constraints, and baseline
   fingerprint as immutable inputs.
2. Inspect only the files needed for the current WorkItem.
3. Implement a coherent patch and run focused offline tests when useful.
4. Never weaken tests, edit OnePTeam run metadata, push, deploy, or expand product scope.
5. Return the required structured summary. It is candidate evidence only.
6. OnePTeam independently computes the diff, reruns gates, reviews the patch, and decides
   whether the WorkItem or Delivery Contract is complete.
