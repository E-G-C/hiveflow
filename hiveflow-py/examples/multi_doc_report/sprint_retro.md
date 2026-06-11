# Sprint 14 Retrospective Notes
Date: 2025-12-13
Facilitator: Carol Liu (Scrum Master)
Attendees: Full mobile team (8 people)

## What went well

- Offline sync MVP landed on time, all 12 acceptance criteria passing
- New hire (David) ramped up fast, delivered US-002 GPS module solo
- Cross-platform code sharing reached 72% (up from 58% in Sprint 12)
- Zero P1 bugs in production for third consecutive sprint
- QA automation coverage at 84% (target was 80%)

## What didn't go well

- IoT WebSocket integration blocked for 6 days waiting on Atlas team API docs
- Form builder prototype was descoped due to underestimated complexity
- Android build times increased to 8 minutes after adding offline module
  (was 4 minutes in Sprint 12)
- Two engineers pulled into P2 production support mid-sprint (12 hours lost)
- Sprint planning took 4 hours instead of budgeted 2 hours

## Discussion highlights

Carol: The Atlas dependency is our biggest risk. We've been blocked twice now
in the last three sprints. Should we build a mock server?

David: I already started a basic mock. It replays recorded WebSocket frames.
Covers about 40% of the message types. Could finish it in 2 days.

Alex: Form builder was always going to be hard. The conditional logic engine
alone is probably 3 sprints of work. We need to break it down further before
committing.

Sarah: The Android build time regression is killing productivity. We should
invest in build caching and modularization. I estimate 2 days to set up
Gradle remote cache.

Bob (PM): From product side, the IoT dashboard is the top priority for the
Q1 release. If we have to choose between form builder and IoT dashboard,
IoT wins. Form builder can slip to v3.1.

## Action items

1. David: Complete Atlas mock server by Sprint 15 Day 3
2. Sarah: Set up Gradle remote build cache by Sprint 15 Day 2
3. Alex: Break down form builder into sub-epics with estimates
4. Carol: Set up dedicated office hours with Atlas team (Tuesdays 2-3pm)
5. Bob: Update roadmap to reflect form builder re-scoping

## Sprint 14 velocity

- Committed: 34 story points
- Completed: 28 story points (82%)
- Carried over: 6 points (form builder stories)

## Sprint 15 goals

1. Complete IoT dashboard read-only view (US-003 partial)
2. GPS tracking battery optimization pass
3. Begin form builder conditional logic spike
