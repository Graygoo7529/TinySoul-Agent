"""Fixed narrative wrappers consumed by kernel.interaction."""


def question(
    *,
    text: str,
    options: tuple[tuple[str, str, str], ...],
    allow_other: bool,
    explanation: str,
) -> str:
    lines = ["Agent question:", text]
    if explanation:
        lines.extend(("Explanation:", explanation))
    lines.extend(
        f"- {label} [{identity}]" + (f": {description}" if description else "")
        for identity, label, description in options
    )
    if options:
        lines.append(
            "You may also answer in your own words."
            if allow_other
            else "Choose one of these options."
        )
    return "\n".join(lines)


def reply(
    *,
    question: str,
    text: str,
    selected: str = "",
    description: str = "",
    comment: str = "",
) -> str:
    lines = [f"In reply to: {question}"]
    if selected:
        lines.append(f"User selected: {selected}")
        if description:
            lines.append(description)
        if comment:
            lines.append(f"User comment: {comment}")
    else:
        lines.append(f"User answer: {text}")
    return "\n".join(lines)


def input_text(*, text: str, initial: bool) -> str:
    return ("User input:\n" if initial else "User added:\n") + text
