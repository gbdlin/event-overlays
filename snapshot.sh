#!/bin/bash
echo "AAAAAAAAAA"
/home/gwynbleidd/.local/share/poetry/bin/poetry -C /home/gwynbleidd/Projects/pykonik/obs-overlays run python /home/gwynbleidd/Projects/pykonik/obs-overlays/snapshot.py "$@"
