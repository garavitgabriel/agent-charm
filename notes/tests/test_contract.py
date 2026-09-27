from datetime import UTC, datetime

from charm_notes import Book, FakeNoteStore, Note


async def test_fake_store_confirms_and_fails() -> None:
    note = Note("Foxes win because they change their minds.", datetime.now(UTC), "en",
                Book("Superforecasting", "Philip Tetlock", "3"))
    store = FakeNoteStore()
    receipt = await store.save(note)
    assert receipt.ok and store.saved == [note]
    store.fail = "vault unreachable"
    receipt = await store.save(note)
    assert not receipt.ok and receipt.error == "vault unreachable" and len(store.saved) == 1
