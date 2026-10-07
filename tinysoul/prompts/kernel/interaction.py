"""Fixed narrative wrappers consumed by kernel.interaction."""


def question(
    *,
    text: str,
    options: tuple[tuple[str, str, str], ...],
    allow_other: bool,
) -> str:
    return "\n".join(
        body
        for _, body in question_parts(
            text=text, options=options, allow_other=allow_other
        )
    )


def question_parts(
    *, text: str, options: tuple[tuple[str, str, str], ...], allow_other: bool
) -> tuple[tuple[str, str], ...]:
    parts = [("Agent question", "Agent question:\n" + text)]
    parts.extend(
        (
            f"{label} [{identity}]",
            f"- {label} [{identity}]" + (f": {description}" if description else ""),
        )
        for identity, label, description in options
    )
    if options:
        parts.append(
            (
                "Answer policy",
                "You may also answer in your own words."
                if allow_other
                else "Choose one of these options.",
            )
        )
    return tuple(parts)


def reply_parts(
    *,
    question: str,
    text: str,
    selected: str = "",
    description: str = "",
    comment: str = "",
) -> tuple[tuple[str, str], ...]:
    parts = [("Associated question", f"In reply to: {question}")]
    if selected:
        parts.append(("User selection", f"User selected: {selected}"))
        if description:
            parts.append(("Selected option description", description))
        if comment:
            parts.append(("User comment", f"User comment: {comment}"))
    else:
        parts.append(("User answer", f"User answer: {text}"))
    return tuple(parts)


def input_text(*, text: str, initial: bool) -> str:
    return ("User input:\n" if initial else "User added:\n") + text


def question_title(question: str) -> str:
    return f"Agent question: {question}"


def reply_title(question: str, answer: str) -> str:
    return f"User reply: {question} / {answer}"


def input_title(initial: bool) -> str:
    return "User input" if initial else "User append"
