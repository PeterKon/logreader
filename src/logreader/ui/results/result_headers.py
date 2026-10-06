from textwrap import fill


def scan_limit_operations(limit, total):
    message = fill(
        f"WARNING: Only {limit:,} of this file’s {total:,} lines were scanned because of the "
        '"Max lines scanned" setting. The scanner reads from the end/tail of the file, '
        f'so these results cover the last {limit:,} lines. The earlier lines were not '
        'scanned, and any matches in those lines are not included in these results.',
        width=100,
    ) + "\n\n" + fill(
        'If you want the entire file to be scanned, increase "Max lines scanned" '
        f'to at least {total:,} and press Analyze again. Do note that increasing this '
        'setting will cause more lines to be loaded and scanned. This can increase '
        'analysis and rendering time and will also consume more system memory.',
        width=100,
    )
    return (
        ("WARNING: ", "warning", True),
        (message[len("WARNING: "):] + "\n\n", "muted", False),
    )
