"""
Average dog weight tool.
"""


def average_dog_weight(name: str) -> str:
    """
    Returns average weight of a dog when given the breed.

    Args:
        name: Dog breed name

    Returns:
        Description of average weight for the breed
    """
    if name == "Scottish Terrier":
        return "Scottish Terriers average 20 lbs"
    elif name == "Border Collie":
        return "a Border Collies average weight is 37 lbs"
    elif name == "Toy Poodle":
        return "a toy poodles average weight is 7 lbs"
    else:
        return "An average dog weights 50 lbs"
