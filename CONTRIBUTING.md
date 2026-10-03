# Contributing

Thanks for looking. Agent Charm is a small hobby project; issues and pull requests are welcome.

## Before you open a PR

- **Run the checks for what you touched** (CI runs them all):
  - `cd server && uv run ruff check . && uv run mypy src && uv run pytest -q`
  - `cd notes && uv run pytest -q` · `cd feeds && uv run pytest -q`
  - `cd tools && uv run ruff check . && uv run mypy src && uv run pytest -q`
  - `cmake -S sim -B build/sim && cmake --build build/sim && ctest --test-dir build/sim --output-on-failure`
  - `cd firmware && pio run -e charm && pio test -e native`
- **UI changes** pass the pre-merge checklist in [`docs/BRIEF.md` § 11.6](docs/BRIEF.md) on the
  simulator (`./build/sim/charm-sim --shots out/shots`), and implement from the final renders in
  `docs/design/final/`.
- **Wire changes** go through [`docs/PROTOCOL.md`](docs/PROTOCOL.md) and `contract/` first, in the
  same PR, with the server, sim and firmware updated together.
- Commits: `area: brief description` (e.g. `server: stream the second sentence sooner`).

## Non-negotiables

- **Honesty.** Never show listening unless the mic is capturing; never show Done/Saved before the
  backend confirms; stale data says it's stale; money needs a ≥2 s hold on a preview; the charm is
  read-and-converse only.
- **No secrets or personal data in git.** Wi-Fi passwords, `CHARM_TOKEN`, API keys and your own
  feeds stay in `secrets.h` / `.env` / `.local/`, all gitignored. Test fixtures are synthetic.
- Vendored code keeps its license and a provenance note; add it to
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

By contributing you agree your work is licensed under the repository's [MIT license](LICENSE).
