"""The frozen fork point, single-sourced.

`git merge-base HEAD master` collapses to HEAD the moment this work lands, and
every gate that derived a range from it then went either vacuous or red:

  * G1 could no longer find an implementation commit (refused, correctly).
  * G4 saw zero appended migrations, because master now contains them.
  * G9 linted an empty file list and passed on nothing.

Round 3 caught the last of those. The other two surfaced immediately after the
merge. All three are the same bug, so the constant lives in one place rather
than being retyped into three checkers -- retyped constants drifting apart is
the defect this session spent three review rounds removing.

This is the commit origin/master pointed at when the work began.
"""

FORK_SHA = "6c8c7e3b"
