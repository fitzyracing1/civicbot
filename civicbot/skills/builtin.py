"""Built-in skills: the original 311/status/transit features expressed as skills."""
from __future__ import annotations

# keep in sync with civicbot.robot.matcher.CANONICAL (not imported: avoids a circular import)
REPORT_KEYWORDS = ['abandoned_vehicle', 'animal', 'drainage', 'encampment', 'graffiti', 'needles', 'parking', 'pothole', 'recycling', 'rodent', 'scooter', 'sidewalk', 'sign', 'signal', 'snow', 'streetlight', 'trash', 'tree']

BUILTIN_SKILLS = {
    "city-311-report": {
        "name": "city-311-report", "handler": "builtin:report", "kind": "write",
        "title": "Report a problem to the city (Open311 / SeeClickFix)",
        "description": "Finds the right city 311 API for a place and prepares a service request (dry-run until "
                       "sending is enabled and you reply YES).",
        "triggers": {"keywords": REPORT_KEYWORDS},
    },
    "city-311-status": {
        "name": "city-311-status", "handler": "builtin:status", "kind": "read",
        "title": "Check a 311 request's status",
        "description": "Looks up the status of a request this robot filed: 'status #123'.",
        "triggers": {"keywords": ["status", "update", "progress"]},
    },
    "gtfs-transit": {
        "name": "gtfs-transit", "handler": "builtin:transit", "kind": "read",
        "title": "Next arrivals from a GTFS-Realtime feed",
        "description": "Next arrivals at your configured stop (needs transit_feed_url on the robot profile).",
        "triggers": {"keywords": ["bus", "train", "next", "arrivals", "transit"]},
    },
}
