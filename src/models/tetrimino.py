from enum import Enum

class TetriminoType(Enum):
    I = 1
    O = 2
    T = 3
    S = 4
    Z = 5
    J = 6
    L = 7

TETRIMINO_SHAPES = {
    TetriminoType.I: [
        (0, 0), (1, 0), (2, 0), (3, 0)
    ],
    TetriminoType.O: [
        (0, 0), (1, 0), (0, 1), (1, 1)
    ],
    TetriminoType.T: [
        (0, 0), (1, 0), (2, 0), (1, 1)
    ],
    TetriminoType.S: [
        (1, 0), (2, 0), (0, 1), (1, 1)
    ],
    TetriminoType.Z: [
        (0, 0), (1, 0), (1, 1), (2, 1)
    ],
    TetriminoType.J: [
        (0, 0), (0, 1), (1, 1), (2, 1)
    ],
    TetriminoType.L: [
        (2, 0), (0, 1), (1, 1), (2, 1)
    ],
}
