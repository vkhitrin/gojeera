from textual.geometry import Offset, Region, Spacing


def constrain_dropdown_offset(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    container_region: Region,
) -> Offset:
    constrained_x, constrained_y, _width, _height = Region(x, y, width, height).constrain(
        'inside',
        'none',
        Spacing.all(0),
        container_region,
    )
    return Offset(constrained_x, constrained_y)
