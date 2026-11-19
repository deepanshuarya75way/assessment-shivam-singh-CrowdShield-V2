def risk_score(people):
    people = max(0, int(people))
    score = min(people, 100)

    if score < 30:
        alert = "GREEN"
    elif score < 60:
        alert = "YELLOW"
    elif score < 80:
        alert = "ORANGE"
    else:
        alert = "RED"

    return score, alert


def crowd_status(people, elevated_threshold=15, high_threshold=30):
    people = max(0, int(people))

    if elevated_threshold >= high_threshold:
        raise ValueError(
            "Elevated threshold must be lower than high threshold."
        )

    if people >= high_threshold:
        return "HIGH"

    if people >= elevated_threshold:
        return "ELEVATED"

    return "NORMAL"
