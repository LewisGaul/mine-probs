# April 2018, Lewis Gaul

"""
Minefield widgets.

Exports
-------
.. class:: MinefieldWidget
    The minefield widget class.

"""

__all__ = ("MinefieldWidget",)

import functools
import logging
import zig_minesolver
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QPen, QBrush, QColor
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView, QSizePolicy, QWidget

from .board import Board, Grid
from .types import CellContents, CellImageType, Coord_T
from . import IMG_DIR


logger = logging.getLogger(__name__)

_SUNKEN_CELL = CellContents.Num(0)
_RAISED_CELL = CellContents.Unclicked


def _update_cell_images(
    cell_images: Dict[CellContents, QPixmap],
    size: int,
    styles: Dict[CellImageType, str],
    required: CellImageType = CellImageType.ALL,
) -> None:
    """
    Initialise or update the pixmap images for the minefield cells.

    Arguments:
    cell_images (dict)
        The dictionary to fill with the images.
    size (int)
        The size in pixels to make the image (square).
    required (CellImageType)
        Which images types require updating.
    """
    # Currently only allows setting button styles.
    btn_style = styles[CellImageType.BUTTONS]
    if required & CellImageType.BUTTONS:
        cell_images[_RAISED_CELL] = _make_pixmap(
            "buttons", btn_style, "btn_up.png", size
        )
        cell_images[_SUNKEN_CELL] = _make_pixmap(
            "buttons", btn_style, "btn_down.png", size
        )
    if required & (CellImageType.BUTTONS | CellImageType.NUMBERS):
        for i in range(1, 19):
            cell_images[CellContents.Num(i)] = _make_pixmap(
                "numbers", btn_style, "btn_down.png", size, "num%d.png" % i, 7 / 8
            )
    if required & (CellImageType.BUTTONS | CellImageType.MARKERS):
        for i in range(1, 4):
            cell_images[CellContents.Flag(i)] = _make_pixmap(
                "markers", btn_style, "btn_up.png", size, "flag%d.png" % i, 5 / 8
            )
            cell_images[CellContents.WrongFlag(i)] = _make_pixmap(
                "markers", btn_style, "btn_up.png", size, "cross%d.png" % i, 5 / 8
            )
            cell_images[CellContents.Mine(i)] = _make_pixmap(
                "markers", btn_style, "btn_down.png", size, "mine%d.png" % i, 7 / 8
            )
            cell_images[CellContents.HitMine(i)] = _make_pixmap(
                "markers", btn_style, "btn_down_hit.png", size, "mine%d.png" % i, 7 / 8
            )


def _make_pixmap(
    img_subdir: str,
    style: str,
    bg_fname: str,
    size: int,
    fg_fname: Optional[str] = None,
    propn: float = 1.0,
) -> QPixmap:
    def get_path(subdir, fname, styl) -> str:
        base_path = IMG_DIR / subdir
        full_path = base_path / styl / fname
        if not full_path.exists():
            logger.warning(f"Missing image file at {full_path}, using standard style")
            full_path = base_path / "standard" / fname
        return str(full_path)

    bg_path = get_path("buttons", bg_fname, style)
    if fg_fname:
        image = QImage(bg_path).scaled(
            size, size, transformMode=Qt.SmoothTransformation
        )
        fg_size = int(propn * size)
        fg_path = get_path(img_subdir, fg_fname, "Standard")
        overlay = QPixmap(fg_path).scaled(
            fg_size, fg_size, transformMode=Qt.SmoothTransformation
        )
        painter = QPainter(image)
        margin = int(size * (1 - propn) / 2)
        painter.drawPixmap(margin, margin, overlay)
        painter.end()
        image = QPixmap.fromImage(image)
    else:
        image = QPixmap(bg_path).scaled(
            size, size, transformMode=Qt.SmoothTransformation
        )
    return image


def _filter_left_and_right(mouse_event_func: Callable):
    """
    Decorator for mouse event methods to filter out buttons that aren't the
    standard left or right mouse buttons.
    """

    @functools.wraps(mouse_event_func)
    def wrapper(self, event: QMouseEvent):
        if event.button() not in [Qt.LeftButton, Qt.RightButton, Qt.NoButton]:
            return
        event = QMouseEvent(
            event.type(),
            event.localPos(),
            event.windowPos(),
            event.screenPos(),
            event.button(),
            event.buttons() & (Qt.LeftButton | Qt.RightButton),
            event.modifiers(),
            event.source(),
        )
        return mouse_event_func(self, event)

    return wrapper


def _blend_colours(ratio, high=(255, 0, 0), low=(255, 255, 64)) -> Tuple[int, int, int]:
    return tuple(int(low[i] + ratio * (high[i] - low[i])) for i in range(3))


class MinefieldWidget(QGraphicsView):
    """
    The minefield widget.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        logger.info("Initialising minefield widget")

        self.x_size = 8
        self.y_size = 8
        self.btn_size = 32
        self.board = Board(self.x_size, self.y_size)

        self._cell_images: Dict[CellContents, QPixmap] = {}
        _update_cell_images(
            self._cell_images,
            self.btn_size,
            {
                CellImageType.BUTTONS: "Standard",
                CellImageType.NUMBERS: "Standard",
                CellImageType.MARKERS: "Standard",
            },
        )

        self._scene = QGraphicsScene()
        self.setScene(self._scene)
        self.setStyleSheet("border: 0px")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.setMaximumSize(self.sizeHint())

        # Keep track of mouse button states.
        self._mouse_coord = None
        self._both_mouse_buttons_pressed = False
        self._await_release_all_buttons = False
        self._was_double_left_click = False
        self._unflag_on_right_drag = False

        # Set of coords for cells which are sunken.
        self._sunken_cells: Set[Coord_T] = set()

        self._colours = []

        self.reset()

    # --------------------------------------------------------------------------
    # Qt method overrides
    # --------------------------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(self.x_size * self.btn_size, self.y_size * self.btn_size)

    @_filter_left_and_right
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events."""
        coord = self._coord_from_event(event)

        # If the button pressed here is the only button down, we reset the
        # tracking variables.
        # However, if the click was outside the board, we should wait for all
        # buttons to be released before acknowledging clicks.
        if event.button() == event.buttons():
            self._both_mouse_buttons_pressed = False
            self._await_release_all_buttons = False
            self._was_double_left_click = False
            if not coord:
                self._await_release_all_buttons = True

        if self._was_double_left_click:
            self._await_release_all_buttons = True
            return
        if self._await_release_all_buttons:
            return

        self._mouse_coord = coord

        ## Bothclick
        if event.buttons() == (Qt.LeftButton | Qt.RightButton):
            logger.debug("Both mouse buttons down on cell %s", coord)
            self._both_mouse_buttons_pressed = True
        ## Leftclick
        elif event.button() == Qt.LeftButton:
            logger.debug("Left mouse button down on cell %s", coord)
            assert coord is not None
            self.left_button_down(coord)
        ## Rightclick
        elif event.button() == Qt.RightButton:
            logger.debug("Right mouse button down on cell %s", coord)
            assert coord is not None
            self.right_button_down(coord)

    @_filter_left_and_right
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double clicks."""
        self._mouse_coord = coord = self._coord_from_event(event)

        if (
            event.button() == Qt.LeftButton
            and not self._both_mouse_buttons_pressed
            and coord
        ):
            self._was_double_left_click = True
            self.left_button_double_down(coord)
        else:
            return self.mousePressEvent(event)

    @_filter_left_and_right
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events."""
        coord = self._coord_from_event(event)

        # Return if the mouse wasn't moved to a different cell.
        if self._await_release_all_buttons or coord == self._mouse_coord:
            return

        self._mouse_coord = coord

        ## Double leftclick
        if self._was_double_left_click:
            return

        ## Bothclick
        if event.buttons() & Qt.LeftButton and event.buttons() & Qt.RightButton:
            pass
        elif not self._both_mouse_buttons_pressed:
            ## Leftclick
            if event.buttons() & Qt.LeftButton:
                self.left_button_move(coord)
            ## Rightclick
            if event.buttons() & Qt.RightButton:
                self.right_button_move(coord)

    @_filter_left_and_right
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release events."""
        if self._await_release_all_buttons and not event.buttons():
            self._await_release_all_buttons = False
            return

        coord = self._coord_from_event(event)

        ## Bothclick (one of the buttons still down)
        if self._both_mouse_buttons_pressed:
            pass
        ## Left release
        elif event.button() == Qt.LeftButton and not self._was_double_left_click:
            logger.debug("Left mouse button release on cell %s", coord)
            self.left_button_release(coord)

        # Reset variables if neither of the mouse buttons are down.
        if not event.buttons():
            logger.debug("No mouse buttons down, reset variables")
            self.all_buttons_release()

    # --------------------------------------------------------------------------
    # Mouse click handlers
    # --------------------------------------------------------------------------
    def left_button_down(self, coord: Coord_T) -> None:
        """
        Left mouse button was pressed (single click). Change display and call
        callback functions as appropriate.
        """
        if self.board[coord] is CellContents.Unclicked:
            self._set_cell_image(coord, _SUNKEN_CELL)
            self._sunken_cells.add(coord)

    def left_button_double_down(self, coord: Coord_T) -> None:
        """
        Left button was double clicked. Call callback to remove any flags that
        were on the cell.
        """
        if type(self.board[coord]) is CellContents.Flag:
            self.board[coord] = CellContents.Unclicked
            self._set_cell_image(coord)
        else:
            self._was_double_left_click = False
            self.left_button_down(coord)

    def left_button_move(self, coord: Optional[Coord_T]) -> None:
        """
        Left mouse button was moved after a single click. Change display as
        appropriate.
        """
        self._raise_all_sunken_cells()
        if coord is not None:
            self.left_button_down(coord)

    def left_button_release(self, coord: Coord_T) -> None:
        """
        Left mouse button was released. Change display and call callback
        functions as appropriate.
        """
        self._raise_all_sunken_cells()
        if coord is None:
            return
        if self.board[coord] is CellContents.Unclicked:
            self.board[coord] = CellContents.Num(0)
        elif type(self.board[coord]) is CellContents.Num:
            self.board[coord] += 1
        else:
            return
        self._set_cell_image(coord)
        self._display_probs()

    def right_button_down(self, coord: Coord_T) -> None:
        """
        Right mouse button was pressed. Change display and call callback
        functions as appropriate.
        """
        if self.board[coord] is CellContents.Unclicked:
            self.board[coord] = CellContents.Flag(1)
        elif type(self.board[coord]) is CellContents.Flag:
            if self.board[coord].num == 3:
                return
            self.board[coord] += 1
        elif type(self.board[coord]) is CellContents.Num:
            self.board[coord] = CellContents.Unclicked
        else:
            return
        self._set_cell_image(coord)
        self._display_probs()

    def all_buttons_release(self) -> None:
        """
        The second of the mouse buttons was released after both were pressed.
        """
        self._mouse_coord = None
        self._both_mouse_buttons_pressed = False
        self._await_release_all_buttons = False
        self._was_double_left_click = False

    # --------------------------------------------------------------------------
    # Other methods
    # --------------------------------------------------------------------------
    def _is_coord_in_grid(self, coord: Coord_T) -> bool:
        return self.board.is_coord_in_grid(coord)

    def _coord_from_event(self, event: QMouseEvent) -> Optional[Coord_T]:
        """
        Get cell coordinate from mouse button event.

        :param event:
            The mouse event.
        :return:
            The cell coordinate, or None if outside the board.
        """
        pos = self.mapToScene(event.pos())

        coord = int(pos.x()) // self.btn_size, int(pos.y()) // self.btn_size
        if not self._is_coord_in_grid(coord):
            return None
        return coord

    def _raise_all_sunken_cells(self) -> None:
        """
        Reset all sunken cells to appear raised.
        """
        raise_cells = {
            c for c in self._sunken_cells if self.board[c] is CellContents.Unclicked
        }
        if raise_cells:
            for c in raise_cells:
                self._set_cell_image(c)
        self._sunken_cells.clear()

    def _set_cell_image(
        self, coord: Coord_T, state: Optional[CellContents] = None
    ) -> None:
        """
        Set the image of a cell.

        Arguments:
        coord ((x, y) tuple in grid range)
            The coordinate of the cell.
        state
            The cell_images key for the image to be set.
        """
        if state is None:
            state = self.board[coord]
        if state not in self._cell_images:
            logger.error("Missing cell image for state: %s", state)
            return
        x, y = coord
        b = self._scene.addPixmap(self._cell_images[state])
        b.setPos(x * self.btn_size, y * self.btn_size)

    def _set_cell_colour(self, coord: Coord_T, prob: float) -> None:
        """Set the colour of an unclicked cell based on probability."""
        x, y = coord
        x = x * self.btn_size + 2
        y = y * self.btn_size + 2
        w = self.btn_size - 4
        h = self.btn_size - 4
        pen = QPen(Qt.NoPen)

        density = 8 / (self.x_size * self.y_size)  # TODO
        if prob >= density:
            ratio = (prob - density) / (1 - density)
            colour = _blend_colours(ratio)
        else:
            ratio = (density - prob) / density
            colour = _blend_colours(ratio, high=(0, 255, 0))
        brush = QBrush(QColor(*colour))
        self._colours.append(self._scene.addRect(x, y, w, h, pen, brush))

    def _remove_cell_colours(self) -> None:
        """Remove colouring from unclicked cells."""
        for rect in self._colours:
            self._scene.removeItem(rect)
        self._colours.clear()

    def _display_probs(self) -> None:
        """Display the board's probabilities."""
        self._remove_cell_colours()
        try:
            probs = zig_minesolver.get_board_probs(str(self.board), mines=8, per_cell=3)
        except Exception as e:
            logger.warning("Failed to calculate probabilities, %s", e)
            return
        probs = Grid.from_2d_array(probs)
        print()
        print(probs)
        for coord in self.board.all_coords:
            if self.board[coord] is CellContents.Unclicked:
                self._set_cell_colour(coord, probs[coord])

    def reset(self) -> None:
        """Reset all cell images and other state for a new game."""
        logger.info("Resetting minefield widget")
        self._scene.clear()
        for c in self.board.all_coords:
            self._set_cell_image(c, CellContents.Unclicked)
        self._mouse_coord = None
        self._both_mouse_buttons_pressed = False
        self._await_release_all_buttons = True
        self.board.reset()
