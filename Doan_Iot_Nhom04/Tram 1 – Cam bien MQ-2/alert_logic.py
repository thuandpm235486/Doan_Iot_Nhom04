THRESHOLD_WARNING = 1500
THRESHOLD_DANGER = 2800


def get_status(value):
    if value >= THRESHOLD_DANGER:
        return "DANGER"
    if value >= THRESHOLD_WARNING:
        return "WARNING"
    return "SAFE"
