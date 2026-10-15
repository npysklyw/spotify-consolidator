from app.integrations.spotify.models import SourceOccurrence, SourceTrack


def test_reader_contract_preserves_duplicate_and_unavailable_slots() -> None:
    track = SourceTrack(
        spotify_track_id="abc123", spotify_uri="spotify:track:abc123", name="Example", artists=[]
    )
    entries = [
        SourceOccurrence(position=0, track=track),
        SourceOccurrence(position=1, unavailable_reason="episode"),
        SourceOccurrence(position=2, track=track),
    ]
    assert [entry.position for entry in entries] == [0, 1, 2]
    assert entries[0].track == entries[2].track
    assert entries[1].track is None
    assert entries[1].unavailable_reason == "episode"
