# notes — reading notes store ("save this thought")

Saves the owner's **verbatim** thoughts, with book/chapter context, to the personal OS vault inbox via
the OS knowledge service (`POST /submit` → `inbox/<date>-charm-<slug>.md`, new file only).
The charm server depends on this package through the `NoteStore` interface in
`src/charm_notes/__init__.py` (a chief-owned contract, like `docs/PROTOCOL.md`).

See `.parallel-plans/` for the active build brief.
