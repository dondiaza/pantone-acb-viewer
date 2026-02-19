from pantone_viewer.upload_store import UploadStore


def test_upload_store_roundtrip(tmp_path) -> None:
    store = UploadStore(base_dir=tmp_path)
    session = store.create_session("sample.psd")

    store.append_chunk(session.upload_id, b"abc")
    store.append_chunk(session.upload_id, b"123")
    loaded = store.get_session(session.upload_id)
    assert loaded.size == 6

    done_session, data = store.finalize(session.upload_id)
    assert done_session.filename == "sample.psd"
    assert data == b"abc123"

