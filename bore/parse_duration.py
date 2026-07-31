import re

DEFAULT_TOKEN_LIFETIME = 3600


def parse_duration(value: str) -> int:
    """
    Converts:
        30m -> 1800
        2h  -> 7200
        1d  -> 86400
        90s -> 90
    """

    match = re.fullmatch(r"(\d+)([smhd])", value.lower())

    if not match:
        raise ValueError(
            "Time must look like 30m, 8h, 2d or 45s."
        )

    amount = int(match.group(1))
    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    return amount * multipliers[unit]