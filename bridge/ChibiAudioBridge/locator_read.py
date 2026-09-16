from __future__ import absolute_import, print_function

LOCATOR_READ_METHODS = ("locators",)


def install_locator_read(cls):
    cls._rpc_locators = _rpc_locators


def _rpc_locators(self, params):
    song = self.song()
    limit = params.get("limit")
    limit = 256 if limit is None else int(limit)
    if limit < -1:
        raise ValueError("limit must be -1 or >= 0")

    cue_points = list(getattr(song, "cue_points", []))
    cue_points.sort(key=lambda cue: float(getattr(cue, "time", 0.0)))
    total = len(cue_points)
    selected = cue_points if limit < 0 else cue_points[:limit]
    locators = []
    for index, cue in enumerate(selected):
        obj_id = self._object_id(cue)
        self._remember_object(obj_id, cue)
        locators.append({
            "index": index,
            "id": obj_id,
            "name": getattr(cue, "name", ""),
            "time": float(getattr(cue, "time", 0.0)),
        })

    return {
        "set_signature": self._set_signature(),
        "current_song_time": float(getattr(song, "current_song_time", 0.0)),
        "last_event_time": float(getattr(song, "last_event_time", 0.0)),
        "song_length": float(getattr(song, "song_length", 0.0)),
        "locator_count": total,
        "truncated": limit >= 0 and total > limit,
        "locators": locators,
    }
