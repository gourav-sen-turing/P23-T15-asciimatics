# -*- coding: utf-8 -*-
"""
This module provides `Renderers` to create complex animation effects.  For more details see
http://asciimatics.readthedocs.io/en/latest/rendering.html
"""
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
from builtins import object
from builtins import range
import copy
from random import randint, random
from future.utils import with_metaclass
from abc import ABCMeta, abstractproperty, abstractmethod
from math import sin, cos, pi, sqrt, atan2
from pyfiglet import Figlet, DEFAULT_FONT
from PIL import Image
import re
import json

from wcwidth.wcwidth import wcswidth

from asciimatics.screen import Screen, TemporaryCanvas
from asciimatics.constants import COLOUR_REGEX
from asciimatics.parsers import AnsiTerminalParser, Parser


#: Attribute conversion table for the ${c,a} form of attributes for
#: :py:obj:`~.Screen.paint`.
ATTRIBUTES = {
    "1": Screen.A_BOLD,
    "2": Screen.A_NORMAL,
    "3": Screen.A_REVERSE,
    "4": Screen.A_UNDERLINE,
}


class Renderer(with_metaclass(ABCMeta, object)):
    """
    A Renderer is simply a class that will return one or more text renderings
    for display by an Effect.

    In the simple case, this can be a single string that contains some
    unchanging content - e.g. a simple text message.

    It can also represent a sequence of strings that can be played one after
    the other to make a simple animation sequence - e.g. a rotating globe.
    """

    @abstractproperty
    def max_width(self):
        """
        :return: The max width of the rendered text (across all images if an animated renderer).
        """

    @abstractproperty
    def rendered_text(self):
        """
        :return: The next image and colour map in the sequence as a tuple.
        """

    @abstractproperty
    def images(self):
        """
        :return: An iterator of all the images in the Renderer.
        """

    @abstractproperty
    def max_height(self):
        """
        :return: The max height of the rendered text (across all images if an animated renderer).
        """

    def __repr__(self):
        """
        :returns: a plain string representation of the next rendered image.
        """
        return str(self)

    def __str__(self):
        """
        :returns: a plain string representation of the next rendered image.
        """
        result = self.rendered_text
        if result is None or not isinstance(result, tuple):
            return ""
        text, _ = result
        return "\n".join(text) if text else ""


class StaticRenderer(Renderer):
    """
    A StaticRenderer is a Renderer that can create all possible images in
    advance.  After construction the images will not change, but can by cycled
    for animation purposes.

    This class will also convert text like ${c,a,b} into colour c, attribute a
    and background b for any subsequent text in the line, thus allowing
    multi-coloured text.  The attribute and background are optional.
    """

    # Regular expression for use to find colour sequences in multi-colour text.
    # It should match ${n}, ${m,n} or ${m,n,o}
    _colour_sequence = re.compile(COLOUR_REGEX)

    def __init__(self, images=None, animation=None):
        """
        :param images: An optional set of ascii images to be rendered.
        :param animation: A function to pick the image (from images) to be
                          rendered for any given frame.
        """
        super(StaticRenderer, self).__init__()
        self._images = images if images is not None else []
        self._index = 0
        self._max_width = 0
        self._max_height = 0
        self._animation = animation
        self._colour_map = None
        self._plain_images = []
        self._convert_images()

    def _convert_images(self):
        """
        Convert any images into a more Screen-friendly format.
        """
        self._plain_images = []
        self._colour_map = []

        for image in self._images:
            lines = image.split("\n")
            plain_image = []
            colour_map = []

            for line in lines:
                plain_line = ""
                colour_line = []

                # Current colors for this line
                current_fg = Screen.COLOUR_WHITE
                current_attr = 0
                current_bg = None

                # Parse colour codes in the line
                while line:
                    match = self._colour_sequence.match(line)
                    if match:
                        # Process colour code based on which pattern matched
                        groups = match.groups()
                        if groups[1] is not None:  # 3-parameter version: fg,attr,bg
                            current_fg = int(groups[1])
                            if groups[2] is not None:
                                # ATTRIBUTES is a module-level constant
                                if groups[2] in ATTRIBUTES:
                                    current_attr = ATTRIBUTES[groups[2]]
                                else:
                                    current_attr = int(groups[2])
                            if groups[3] is not None:
                                current_bg = int(groups[3])
                        elif groups[4] is not None:  # 2-parameter version: fg,attr
                            current_fg = int(groups[4])
                            if groups[5] is not None:
                                if groups[5] in ATTRIBUTES:
                                    current_attr = ATTRIBUTES[groups[5]]
                                else:
                                    current_attr = int(groups[5])
                        elif groups[6] is not None:  # 1-parameter version: fg
                            current_fg = int(groups[6])
                        # The remaining text is the last group
                        line = groups[-1]
                    else:
                        # Regular character
                        plain_line += line[0]
                        colour_line.append((current_fg, current_attr, current_bg))
                        line = line[1:]

                plain_image.append(plain_line)
                colour_map.append(colour_line)

                # Update max dimensions
                line_width = wcswidth(plain_line)
                if line_width is None:
                    line_width = len(plain_line)
                self._max_width = max(self._max_width, line_width)

            self._max_height = max(self._max_height, len(lines))
            self._plain_images.append(plain_image)
            self._colour_map.append(colour_map)

    @property
    def images(self):
        """
        :return: An iterator of all the images in the Renderer.
        """
        return iter(self._plain_images)

    @property
    def rendered_text(self):
        """
        :return: The next image and colour map in the sequence as a tuple.
        """
        if not self._plain_images:
            return [], []

        # Get the current image based on animation or cycling
        if self._animation:
            index = self._animation()
            if index is not None:
                index = index % len(self._plain_images)
            else:
                index = self._index
        else:
            index = self._index
            self._index = (self._index + 1) % len(self._plain_images)

        return self._plain_images[index], self._colour_map[index]

    @property
    def max_height(self):
        """
        :return: The max height of the rendered text (across all images if an animated renderer).
        """
        return self._max_height

    @property
    def max_width(self):
        """
        :return: The max width of the rendered text (across all images if an animated renderer).
        """
        return self._max_width


class DynamicRenderer(with_metaclass(ABCMeta, Renderer)):
    """
    A DynamicRenderer is a Renderer that creates each image as requested.  It
    has a defined maximum size on construction.
    """

    def __init__(self, height, width, clear=True):
        """
        :param height: The max height of the rendered image.
        :param width: The max width of the rendered image.
        """
        super(DynamicRenderer, self).__init__()
        self._must_clear = clear
        self._canvas = TemporaryCanvas(height, width)

    def _clear(self):
        """
        Clear the current image.
        """
        # self._canvas.clear_buffer(Screen.COLOUR_WHITE, Screen.A_NORMAL, Screen.COLOUR_BLACK)
        self._canvas.clear_buffer(None, 0, 0)

    def _write(self, text, x, y, colour=Screen.COLOUR_WHITE,
               attr=Screen.A_NORMAL, bg=Screen.COLOUR_BLACK):
        """
        Write some text to the specified location in the current image.

        :param text: The text to be added.
        :param x: The X coordinate in the image.
        :param y: The Y coordinate in the image.
        :param colour: The colour of the text to add.
        :param attr: The attribute of the image.
        :param bg: The background colour of the text to add.

        This is only kept for back compatibility.  Direct access to the canvas methods is
        preferred.
        """
        self._canvas.print_at(text, x, y, colour, attr, bg)

    @property
    def _plain_image(self):
        return self._canvas.plain_image

    @property
    def _colour_map(self):
        return self._canvas.colour_map

    @abstractmethod
    def _render_now(self):
        """
        Common method to render the latest image.

        :returns: A tuple of the plain image and the colour map as per
        :py:meth:`.rendered_text`.
        """

    @property
    def images(self):
        # We can't return all, so just return the latest rendered image.
        return [self.rendered_text[0]]

    @property
    def rendered_text(self):
        if self._must_clear:
            self._clear()
        text, colours = self._render_now()
        if text == [] and colours == []:
            # If render_now returns empty, use canvas content
            text = self._canvas.plain_image
            colours = self._canvas.colour_map
        return text, colours

    @property
    def max_height(self):
        return self._canvas.height

    @property
    def max_width(self):
        return self._canvas.width

    def __str__(self):
        """
        :returns: a plain string representation of the current rendered image.
        """
        text, _ = self.rendered_text
        return "\n".join(text) if text else ""


class FigletText(StaticRenderer):
    """
    This class renders the supplied text using the specified Figlet font.
    See http://www.figlet.org/ for details of available fonts.
    """

    def __init__(self, text, font=DEFAULT_FONT, width=200):
        """
        :param text: The text string to convert with Figlet.
        :param font: The Figlet font to use (optional).
        :param width: The maximum width for this text in characters.
        """
        figlet = Figlet(font=font, width=width)
        super(FigletText, self).__init__(images=[figlet.renderText(text)])


class _ImageSequence(object):
    """
    Simple class to make an iterator for a PIL Image object.
    """

    def __init__(self, im):
        self.im = im

    def __getitem__(self, ix):
        try:
            if ix:
                self.im.seek(ix)
            return self.im
        except EOFError:
            raise IndexError


class ImageFile(StaticRenderer):
    """
    Renderer to convert an image file (as supported by the Python Imaging
    Library) into an ascii grey scale text image.
    """

    # The ASCII grey scale from darkest to lightest.
    _greyscale = ' .:;rsA23hHG#9&@'

    def __init__(self, filename, height=30, colours=8):
        """
        :param filename: The name of the file to render.
        :param height: The height of the text rendered image.
        :param colours: The number of colours the terminal supports.
        """
        # Load and process the image
        img = Image.open(filename)

        # Handle animated images (like GIFs)
        images = []
        for frame in _ImageSequence(img):
            # Convert to greyscale
            frame = frame.convert('L')

            # Calculate dimensions maintaining aspect ratio
            # Note: height parameter is the desired text height minus 1 for the empty line
            text_height = height - 1
            width = int(frame.size[0] * text_height * 2.0 / frame.size[1])
            frame = frame.resize((width, text_height), Image.LANCZOS)

            # Convert to ASCII with inverted greyscale
            pixels = frame.load()
            text_image = ""

            # Add empty first line
            text_image += "\n"

            for y in range(text_height):
                line = ""
                for x in range(width):
                    pixel = pixels[x, y]
                    # Invert the greyscale: 255 -> 0, 0 -> max
                    inverted_pixel = 255 - pixel
                    index = int(inverted_pixel * (len(self._greyscale) - 1) / 255)
                    line += self._greyscale[index]
                text_image += line + "\n" if y < text_height - 1 else line
            images.append(text_image)

        super(ImageFile, self).__init__(images=images)


class ColourImageFile(StaticRenderer):
    """
    Renderer to convert an image file (as supported by the Python Imaging
    Library) into an block image of available colours.

    .. warning::

        This is only compatible with 256-colour terminals.  Results in other
        terminals with reduced colour capabilities are severely restricted.
        Since Windows only has 8 base colours, it is recommended that you
        avoid this renderer on that platform.
    """

    def __init__(self, screen, filename, height=30, bg=Screen.COLOUR_BLACK,
                 fill_background=False, uni=False, dither=False):
        """
        :param screen: The screen to use when displaying the image.
        :param filename: The name of the file to render.
        :param height: The height of the text rendered image.
        :param bg: The default background colour for this image.
        :param fill_background: Whether to set background colours too.
        :param uni: Whether to use unicode box characters or not.
        :param dither: Whether to dither the rendered image or not.
        """
        # Load and process the image
        img = Image.open(filename)

        # Handle animated images
        images = []
        for frame in _ImageSequence(img):
            # Convert to RGB
            frame = frame.convert('RGB')

            # Calculate dimensions maintaining aspect ratio
            width = int(frame.size[0] * height * 2.0 / frame.size[1])
            frame = frame.resize((width, height), Image.LANCZOS)

            # Convert to coloured text using unicode block characters
            pixels = frame.load()
            text_image = ""
            for y in range(height):
                line = ""
                for x in range(width):
                    r, g, b = pixels[x, y]
                    # Map RGB to terminal colour
                    if screen.colours >= 256:
                        # Use 256 colour mode - map RGB to xterm-256 palette
                        colour = 16 + (r * 5 // 255) * 36 + (g * 5 // 255) * 6 + (b * 5 // 255)
                    else:
                        # Use basic 16 colours
                        colour = 0
                        if r > 128:
                            colour |= 1
                        if g > 128:
                            colour |= 2
                        if b > 128:
                            colour |= 4

                    # Use unicode block character or space
                    char = u"█" if uni else " "
                    if fill_background:
                        line += "${%d,%d,%d}%s" % (colour, 0, colour, char)
                    else:
                        line += "${%d,0,%d}%s" % (colour, bg, char)

                text_image += line + "\n" if y < height - 1 else line
            images.append(text_image)

        super(ColourImageFile, self).__init__(images=images)


class SpeechBubble(StaticRenderer):
    """
    Renders supplied text into a speech bubble.
    """

    def __init__(self, text, tail=None, uni=False):
        """
        :param text: The text to be put into a speech bubble.
        :param tail: Where to put the bubble callout tail, specifying "L" or
                     "R" for left or right tails.  Can be None for no tail.
        """
        max_len = max([wcswidth(x) if wcswidth(x) else len(x) for x in text.split("\n")])
        if uni:
            bubble = "╭─" + "─" * max_len + "─╮\n"
            for line in text.split("\n"):
                filler = " " * (max_len - len(line))
                bubble += "│ " + line + filler + " │\n"
            bubble += "╰─" + "─" * max_len + "─╯"
        else:
            bubble = ".-" + "-" * max_len + "-.\n"
            for line in text.split("\n"):
                filler = " " * (max_len - len(line))
                bubble += "| " + line + filler + " |\n"
            bubble += "`-" + "-" * max_len + "-`"
        if tail == "L":
            bubble += "\n"
            bubble += "  )/  \n"
            bubble += "-\"`\n"
        elif tail == "R":
            bubble += "\n"
            bubble += (" " * max_len) + "\\(  \n"
            bubble += (" " * max_len) + " `\"-\n"
        super(SpeechBubble, self).__init__(images=[bubble])


class Box(StaticRenderer):
    """
    Renders a simple box using ASCII characters.  This does not render in
    extended box drawing characters as that requires non-ASCII characters in
    Windows and direct access to curses in Linux.
    """

    def __init__(self, width, height, uni=False):
        """
        :param width: The desired width of the box.
        :param height: The desired height of the box.
        :param uni: Whether to use unicode box characters or not.
        """
        if uni:
            box = u"┌" + u"─" * (width - 2) + u"┐\n"
            for _ in range(height - 2):
                box += u"│" + u" " * (width - 2) + u"│\n"
            box += u"└" + u"─" * (width - 2) + u"┘\n"
        else:
            box = "+" + "-" * (width - 2) + "+\n"
            for _ in range(height - 2):
                box += "|" + " " * (width - 2) + "|\n"
            box += "+" + "-" * (width - 2) + "+\n"
        super(Box, self).__init__(images=[box])


class Rainbow(StaticRenderer):
    """
    Chained renderer to add rainbow colours to output of another renderer.
    The embedded rendered must not use multi-colour mode (i.e. ${c,a}
    syntax) as this will be converted to explicit text by this renderer.
    """

    # Colour palette when limited to 8 colours (3 bits).
    _palette8 = [1, 1, 3, 3, 2, 2, 6, 6, 4, 4, 5, 5]

    # Colour palette when limited to 256 colours (8 bits).
    _palette256 = [196, 202, 208, 214, 220, 226,
                   154, 118, 82, 46,
                   47, 48, 49, 50, 51,
                   45, 39, 33, 27, 21,
                   57, 93, 129, 165, 201]

    def __init__(self, screen, renderer):
        """
        :param screen: The screen to use when displaying the image.
        :param renderer: The renderer to wrap.
        """
        super(Rainbow, self).__init__()
        palette = self._palette256 if screen.colours == 256 else self._palette8
        for image in renderer.images:
            new_image = ""
            for line in image:
                for i, c in enumerate(line):
                    new_image += "${%d}%s" % (palette[i * len(palette) // 80], c)
                new_image += "\n"
            self._images.append(new_image[:-1])


class BarChart(DynamicRenderer):
    """
    Renderer to create a bar chart using the specified functions as inputs for
    each entry.  Can be used to chart distributions or for more graphical
    effect - e.g. to imitate a sound equalizer or a progress indicator.
    """

    # Character options for rendering bar charts.
    _uni_chars = [
        " ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"
    ]
    _ascii_chars = " .:;rsA23hHG#9&@"
    _uni_bar = "█"
    _ascii_bar = "#"

    def __init__(self, height, width, functions, char="#", colour=Screen.COLOUR_GREEN,
                 bg=Screen.COLOUR_BLACK, gradient=None, scale=None, axes=0,
                 intervals=None, labels=False, border=True, keys=None):
        """
        :param height: Height of the box to contain the bar chart.
        :param width: Width of the box to contain the bar chart.
        :param functions: List of functions to chart.  These should return a
                          value between 0.0 and 1.0 (i.e. a percentage).  If
                          the function returns None, a blank cell will be
                          rendered.
        :param char: Character to use for the bar.  Defaults to "#", but
                     also supports u"█" for a more solid (unicode) block.
        :param colour: Default colour to use for the bars.  This is ignored if
                       a gradient is supplied.
        :param bg: Background colour to use for the bars.  This is ignored if
                   a gradient is supplied.
        :param gradient: Colour gradient to use for the bars.  This is a list
                         of tuple pairs specifying a threshold and a colour,
                         or triplets to include a background colour too.
                         Values are linearly interpolated between thresholds.
        :param scale: Maximum value for the bars.  This is used to scale
                      the function values to the maximum height of the
                      bar.  Any value over the scale will be truncated when
                      displayed.
        :param axes: Which axes to draw.
        :param intervals: Units for interval markers on the axes.
                          Specify a single value for both vertical and horizontal
                          units.  Specify 2 values for vertical and horizontal
                          units.  Defaults to none.
        :param labels: Whether to draw size of the bar at the end.
        :param border: Whether to draw a border for the chart.
        :param keys: Optional keys to name each bar in the chart.
        """
        super(BarChart, self).__init__(height, width, clear=False)
        self._functions = functions
        self._char = char
        if self._char == u"█":
            self._chars = self._uni_chars
            self._bar = self._uni_bar
        else:
            self._chars = self._ascii_chars
            self._bar = self._ascii_bar
        self._colour = colour
        self._bg = bg
        self._gradient = gradient
        self._scale = scale if scale else 1.0
        self._axes = axes
        self._intervals = intervals
        self._labels = labels
        self._border = border
        self._keys = keys

    def _render_now(self):
        # Don't do anything if we have no functions to render.
        if len(self._functions) <= 0:
            return self._plain_image, self._colour_map

        # Blank out the back-buffer.
        self._clear()

        # Figure out the number of columns - including axes lines as needed.
        if not self._border:
            columns = self._canvas.width
        else:
            columns = self._canvas.width - 2

        # Determine the row height - remember to handle Widgets with 0 height.
        if self._canvas.height == 0:
            return self._plain_image, self._colour_map
        row_height = self._canvas.height if not self._border else self._canvas.height - 2

        # Create the data for the chart.
        data = []
        for i in range(columns):
            if i * len(self._functions) // columns < len(self._functions):
                fn = i * len(self._functions) // columns
                value = self._functions[fn]()
                data.append((value, fn))
            else:
                data.append((None, None))

        # First draw the border
        if self._border:
            self._write("+" + "-" * columns + "+", 0, 0, self._colour)
            for line in range(1, self._canvas.height - 1):
                self._write("|", 0, line, self._colour)
                self._write("|", self._canvas.width - 1, line, self._colour)
            self._write("+" + "-" * columns + "+", 0, self._canvas.height - 1, self._colour)

        for x, (value, fn) in enumerate(data):
            if value is None:
                continue

            # First draw the bars
            if self._gradient:
                # Use the gradient colours
                fg_colour = 0
                bg_colour = None
                last = 0
                for entry in self._gradient:
                    threshold = entry[0]
                    if value >= threshold:
                        if len(entry) > 2:
                            fg_colour = entry[1]
                            bg_colour = entry[2]
                        else:
                            fg_colour = entry[1]
                    else:
                        if len(entry) > 2:
                            blend = (value - last) / (threshold - last)
                            fg_colour = self._blend(fg_colour, entry[1], blend)
                            bg_colour = self._blend(bg_colour, entry[2], blend)
                        else:
                            blend = (value - last) / (threshold - last)
                            fg_colour = self._blend(fg_colour, entry[1], blend)
                        break
                    last = threshold
            else:
                fg_colour = self._colour
                bg_colour = self._bg

            # Round to nearest block (allow for scale - rounding up to 1.0)
            used = min(len(self._chars) - 1, int((value / self._scale) * row_height * len(self._chars)))
            bar = used // len(self._chars)
            tail = used % len(self._chars)

            # Now draw the full bars and tails
            for y in range(bar):
                self._write(self._bar,
                            x + (1 if self._border else 0),
                            self._canvas.height - y - (2 if self._border else 1),
                            fg_colour, bg=bg_colour)
            if bar < row_height and tail > 0:
                self._write(self._chars[tail],
                            x + (1 if self._border else 0),
                            self._canvas.height - bar - (2 if self._border else 1),
                            fg_colour, bg=bg_colour)

        # Now add any labels
        if self._labels:
            for x, (value, fn) in enumerate(data):
                if value is None:
                    continue
                # Round to nearest block (allow for scale - rounding up to 1.0)
                used = min(len(self._chars) - 1, int((value / self._scale) * row_height * len(self._chars)))
                bar = used // len(self._chars)
                text = "{:.1f}".format(value)
                self._write(text,
                            x + (1 if self._border else 0) - len(text) // 2,
                            self._canvas.height - bar - (3 if self._border else 2),
                            Screen.COLOUR_WHITE)

        # Now add any interval markers
        if self._intervals:
            if isinstance(self._intervals, int):
                y_interval = self._intervals
                x_interval = self._intervals
            else:
                y_interval = self._intervals[0]
                x_interval = self._intervals[1]

            # Draw the vertical intervals.
            if y_interval:
                for y in range(y_interval, int(self._scale) + 1, y_interval):
                    ty = self._canvas.height - (y * row_height / self._scale) - (2 if self._border else 1)
                    if ty >= 0:
                        for x in range(self._canvas.width):
                            self._write("-", x, int(ty), Screen.COLOUR_BLACK, bg=Screen.COLOUR_WHITE)

            # Draw the horizontal intervals.

        return self._plain_image, self._colour_map

    @staticmethod
    def _blend(a, b, blend):
        """
        Blend from one colour to another.

        :param a: Colour to blend from (or None if not defined).
        :param b: Colour to blend to.
        :param blend: Weighting for the blend (0.0-1.0).
        """
        if a is None:
            return b
        return int(a * (1.0 - blend) + b * blend)


class Fire(DynamicRenderer):
    """
    Renderer to create a fire effect based on a specified `emitter` that
    defines the heat source.

    The implementation here uses the same techniques described in
    http://freespace.virgin.net/hugo.elias/models/m_fire.htm, although a
    slightly different implementation.
    """

    _COLOURS_16 = [
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_WHITE, Screen.A_BOLD),
    ]

    _COLOURS_256 = [
        (0, 0),
        (52, 0),
        (88, 0),
        (124, 0),
        (160, 0),
        (196, 0),
        (202, 0),
        (208, 0),
        (214, 0),
        (220, 0),
        (226, 0),
        (227, 0),
        (228, 0),
        (229, 0),
        (230, 0),
        (231, 0),
    ]

    _CHARS = " ...::$$$&&&@@"

    def __init__(self, height, width, emitter, intensity, spot, colours,
                 bg=False):
        """
        :param height: Height of the box to contain the flames.
        :param width: Width of the box to contain the flames.
        :param emitter: Heat source for the flames.  Any non-whitespace
            character is treated as part of the heat source.
        :param intensity: The strength of the flames.  The bigger the number,
            the hotter the fire.  0 <= intensity <= 1.0.
        :param spot: Heat of each spot source.  Must be an integer > 0.
        :param colours: Number of colours the screen supports.
        :param bg: (Optional) Whether to render background colours only.
        """
        super(Fire, self).__init__(height, width)
        self._emitter = emitter
        self._intensity = intensity
        self._spot_heat = spot
        self._count = len([c for c in emitter if c not in " \n"])
        line = [0 for _ in range(self._canvas.width)]
        self._buffer = [copy.deepcopy(line) for _ in range(self._canvas.width * 2)]
        self._colours = self._COLOURS_256 if colours >= 256 else \
            self._COLOURS_16
        self._bg_too = bg

    def _render_now(self):
        # First make the fire rise with convection
        for y in range(len(self._buffer) - 1):
            self._buffer[y] = self._buffer[y + 1]
            self._buffer[y][randint(0, self._canvas.width - 1)] = 0

        # Seed new hot spots
        x = 0
        line = []
        for c in self._emitter:
            if c == " ":
                line.append(0)
            elif c == "\n":
                x = 0
            else:
                line.append(randint(0, self._spot_heat))
            x += 1
        self._buffer[len(self._buffer) - 1] = line

        # Simulate cooling effect of neighbours.
        cooled = []
        for y in range(1, len(self._buffer) - 1):
            cooled_line = []
            for x in range(1, self._canvas.width - 1):
                average = (self._buffer[y][x - 1] +
                           self._buffer[y][x + 1] +
                           self._buffer[y - 1][x] +
                           self._buffer[y + 1][x] +
                           self._buffer[y][x]) / 5.0
                cooled_line.append(average)
            cooled.append(cooled_line)

        # Tune the cooling effect.
        for y in range(len(cooled)):
            new_line = []
            for x in range(self._canvas.width):
                if x == 0 or x == self._canvas.width - 1:
                    new_line.append(0)
                else:
                    new_line.append(
                        cooled[y][x - 1] * (1.0 - self._intensity) -
                        (1.0 - self._intensity) * 0.3)
            self._buffer[y + 1] = new_line

        # Covert the buffer to a height x width grid.
        self._clear()
        for x in range(self._canvas.width - 1):
            for y in range(len(self._buffer)):
                if self._buffer[y][x] > 0:
                    colour = self._colours[min(len(self._colours) - 1,
                                               self._buffer[y][x])]
                    if self._bg_too:
                        char = " "
                        bg = colour[0]
                    else:
                        char = self._CHARS[min(len(self._CHARS) - 1,
                                           self._buffer[y][x])]
                        bg = 0
                    self._write(char, x, y, colour[0], colour[1], bg)

        return self._plain_image, self._colour_map


class Plasma(DynamicRenderer):
    """
    Renderer to create a "plasma" effect using sinusoidal functions.

    The implementation here uses the same techniques described in
    http://lodev.org/cgtutor/plasma.html
    """

    # Colour palette for 8 and 256 colour rendering.
    _palette_8 = [
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_WHITE, Screen.A_BOLD),
        (Screen.COLOUR_WHITE, Screen.A_BOLD),
        (Screen.COLOUR_WHITE, Screen.A_BOLD),
        (Screen.COLOUR_WHITE, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_YELLOW, Screen.A_BOLD),
        (Screen.COLOUR_RED, Screen.A_BOLD),
        (Screen.COLOUR_RED, 0),
        (Screen.COLOUR_RED, 0),
    ]

    _palette_256 = [
        (16, 0),
        (17, 0),
        (18, 0),
        (19, 0),
        (20, 0),
        (21, 0),
        (21, 0),
        (57, 0),
        (57, 0),
        (93, 0),
        (93, 0),
        (129, 0),
        (129, 0),
        (165, 0),
        (165, 0),
        (201, 0),
        (201, 0),
        (200, 0),
        (199, 0),
        (198, 0),
        (197, 0),
        (196, 0),
        (196, 0),
        (196, 0),
    ]

    def __init__(self, height, width, colours):
        """
        :param height: Height of the box to contain the plasma.
        :param width: Width of the box to contain the plasma.
        :param colours: Number of colours the screen supports.
        """
        super(Plasma, self).__init__(height, width)
        self._palette = self._palette_256 if colours >= 256 else self._palette_8
        self._t = 0

    _greyscale = '.:;rsA23hHG#9&@'

    def _render_now(self):
        # Internal function for creating a sine wave radiating out from a point
        def f(x1, y1, xp, yp, n):
            return sin(sqrt((x1 - self._canvas.width * xp) ** 2 +
                            4 * ((y1 - self._canvas.height * yp) ** 2)) * pi / n)

        self._t += 1
        for y in range(self._canvas.height - 1):
            for x in range(self._canvas.width - 1):
                value = abs(f(x + self._t / 3, y, 1 / 4, 1 / 3, 15) +
                            f(x, y, 1 / 8, 1 / 5, 11) +
                            f(x, y + self._t / 3, 1 / 2, 1 / 5, 13) +
                            f(x, y, 3 / 4, 4 / 5, 13)) / 4.0
                fg, attr = self._palette[
                    int(round(value * (len(self._palette) - 1)))]
                char = self._greyscale[int((len(self._greyscale) - 1) * value)]
                self._write(char, x, y, fg, attr, 0)

        return self._plain_image, self._colour_map


class RotatedDuplicate(StaticRenderer):
    """
    Chained renderer to add a rotated version of the original renderer underneath and centre the
    whole thing within within the specified dimensions.
    """

    def __init__(self, width, height, renderer):
        """
        :param width: The maximum width of the rendered text.
        :param height: The maximum height of the rendered text.
        :param renderer: The renderer to wrap.
        """

        # Get the original images from the wrapped renderer
        original_images = list(renderer.images)
        rotated_images = []

        for original in original_images:
            # Create a new image with both original and rotated versions
            lines = []

            # Calculate centering offsets
            orig_height = len(original)
            orig_width = max(len(line) for line in original) if original else 0
            total_height = orig_height * 2  # Original + rotated

            # Center vertically
            v_offset = (height - total_height) // 2

            # If content is taller than available height, we need to crop
            if v_offset < 0:
                # Skip lines from the top
                skip_top = -v_offset
            else:
                skip_top = 0
                # Add top padding - use single space for empty lines
                for _ in range(v_offset):
                    lines.append(" ")

            # Add original image (centered horizontally)
            h_offset = (width - orig_width) // 2
            lines_added = 0

            # Add original lines (skip if needed)
            for i, line in enumerate(original):
                if i < skip_top:
                    continue
                if len(lines) >= height:
                    break

                if h_offset >= 0:
                    # Padding case - center the line
                    padded_line = " " * h_offset + line + " " * (width - h_offset - len(line))
                    lines.append(padded_line[:width])
                else:
                    # Clipping case - take from the center of the line
                    start = (-h_offset)
                    lines.append(line[start:start + width] if start < len(line) else "")

            # Add rotated image (180 degrees - upside down and reversed)
            reversed_original = list(reversed(original))
            for i, line in enumerate(reversed_original):
                if i + len(original) < skip_top:
                    continue
                if len(lines) >= height:
                    break

                reversed_line = line[::-1]  # Reverse the line
                if h_offset >= 0:
                    # Padding case - center the line
                    padded_line = " " * h_offset + reversed_line + " " * (width - h_offset - len(reversed_line))
                    lines.append(padded_line[:width])
                else:
                    # Clipping case - take from the center of the line
                    start = (-h_offset)
                    lines.append(reversed_line[start:start + width] if start < len(reversed_line) else "")

            # Add bottom padding - use single space for empty lines
            while len(lines) < height:
                lines.append(" ")

            # Join and limit to requested height
            rotated_images.append("\n".join(lines[:height]))

        super(RotatedDuplicate, self).__init__(images=rotated_images)


class Kaleidoscope(DynamicRenderer):
    """
    Renderer to create a 2-mirror kaleidoscope effect.

    This is a chained renderer (i.e. it acts upon the output of another Renderer which is
    passed to it on construction).  The other Renderer is used as the cell that is rotated over
    time to create the animation.

    Since most Renderers don't support partial line display, this Renderer will start with a
    blank canvas and gradually reveal the requested renderer over time.  Similarly it will
    leave the last fully rendered image on exit.
    """

    def __init__(self, height, width, renderer, offset):
        """
        :param height: Height of the box to contain the kaleidoscope.
        :param width: Width of the box to contain the kaleidoscope.
        :param renderer: The renderer to use as the backing image.
        :param offset: Start offset for the render cycle.
        """
        super(Kaleidoscope, self).__init__(height, width)
        self._renderer = renderer
        self._angle = offset * 10 * pi / 180
        self._radius = min(height, width)
        self._x_origin = width // 2
        self._y_origin = height

    def _render_now(self):
        # Start by clearing the existing text
        self._clear()

        # Figure out centre points for each reflection.
        x1, y1 = self._x_origin, self._y_origin
        x2, y2 = self._x_origin + self._radius * sin(self._angle), \
                 self._y_origin - self._radius * cos(self._angle)
        x3, y3 = self._x_origin - self._radius * sin(self._angle), \
                 self._y_origin - self._radius * cos(self._angle)

        # Restrict the area of interest to cut down on processing.
        min_x = max(0, min(x1, x2, x3) - self._renderer.max_width)
        min_y = max(0, min(y1, y2, y3) - self._renderer.max_height)
        max_x = min(self._canvas.width,
                    max(x1, x2, x3) + self._renderer.max_width)
        max_y = min(self._canvas.height,
                    max(y1, y2, y3) + self._renderer.max_height)

        # Now draw the kaleidoscope, by mirroring across each pair of lines.
        data = self._renderer.rendered_text
        for x in range(min_x, max_x):
            for y in range(min_y, max_y):
                # First look at first reflection in the mirror
                rx1 = cos(self._angle) * (x - x1) + sin(self._angle) * (y - y1)
                ry1 = sin(self._angle) * (x - x1) - cos(self._angle) * (y - y1)

                # If we're in the first segment, just draw that.
                if rx1 >= 0:
                    if rx1 < len(data[0][0]):
                        cell = data[0][int(ry1) % len(data[0])][int(rx1)]
                        self._write(data[0][int(ry1) % len(data[0])][int(rx1)],
                                    x, y,
                                    colour=data[1][int(ry1) % len(data[0])][int(rx1)][0])
                    continue

                # Next look at second reflection
                rx2 = cos(self._angle) * (x - x2) - sin(self._angle) * (y - y2)
                ry2 = -sin(self._angle) * (x - x2) - cos(self._angle) * (y - y2)

                # If we're in the second segment, draw that.
                if rx2 >= 0:
                    if rx2 < len(data[0][0]):
                        cell = data[0][int(ry2) % len(data[0])][int(rx2)]
                        self._write(data[0][int(ry2) % len(data[0])][int(rx2)],
                                    x, y,
                                    colour=data[1][int(ry2) % len(data[0])][int(rx2)][0])
                    continue

                # Last option - we must be in the third segment.
                rx3 = cos(self._angle) * (x3 - x) - sin(self._angle) * (y3 - y)
                ry3 = sin(self._angle) * (x3 - x) - cos(self._angle) * (y3 - y)
                if 0 <= rx3 < len(data[0][0]):
                    cell = data[0][int(ry3) % len(data[0])][int(rx3)]
                    self._write(data[0][int(ry3) % len(data[0])][int(rx3)],
                                x, y,
                                colour=data[1][int(ry3) % len(data[0])][int(rx3)][0])

        # Remember to update the rotating kaleidoscope.
        self._angle -= pi / 180

        return self._plain_image, self._colour_map


class AbstractScreenPlayer(DynamicRenderer):
    """
    Abstract renderer to play terminal text with support for ANSI control codes.
    """

    def __init__(self, height, width):
        """
        :param height: required height of the renderer.
        :param width: required width of the renderer.
        """
        super(AbstractScreenPlayer, self).__init__(height, width, clear=False)
        self._parser = AnsiTerminalParser()
        self._current_colours = [Screen.COLOUR_WHITE, Screen.A_NORMAL, Screen.COLOUR_BLACK]
        self._show_cursor = False
        self._cursor_x = 0
        self._cursor_y = 0
        self._save_cursor_x = 0
        self._save_cursor_y = 0
        self._counter = 0
        self._next = 0
        self._buffer = None
        self._parser.reset("", self._current_colours)
        self._clear()

    def _play_content(self, text):
        """
        Process new raw text.

        :param text: thebraw text to be processed.
        """
        lines = text.split("\n")
        for i, line in enumerate(lines):
            self._parser.append(line)
            for _, command, params in self._parser.parse():
                # logging.debug("Command: {} {}".format(command, params))
                if command == Parser.DISPLAY_TEXT:
                    # Just display the text...  allowing for line wrapping.
                    if self._cursor_x + len(params) >= self._canvas.width:
                        part_1 = params[:self._canvas.width - self._cursor_x]
                        part_2 = params[self._canvas.width - self._cursor_x:]
                        self._print_at(part_1, self._cursor_x, self._cursor_y)
                        self._print_at(part_2, 0, self._cursor_y + 1)
                        self._cursor_x = len(part_2)
                        self._cursor_y += 1
                        if self._cursor_y - self._canvas.start_line >= self._canvas.height:
                            self._canvas.scroll()
                    else:
                        self._print_at(params, self._cursor_x, self._cursor_y)
                        self._cursor_x += len(params)
                elif command == Parser.CHANGE_COLOURS:
                    # Change current text colours.
                    self._current_colours = params
                elif command == Parser.NEXT_TAB:
                    # Move to next tab stop - hard-coded to default of 8 characters.
                    self._cursor_x = (self._cursor_x // 8) * 8 + 8
                elif command == Parser.MOVE_RELATIVE:
                    # Move cursor relative to current position.
                    self._cursor_x += params[0]
                    self._cursor_y += params[1]
                    if self._cursor_y < self._canvas.start_line:
                        self._canvas.scroll(self._cursor_y - self._canvas.start_line)
                elif command == Parser.MOVE_ABSOLUTE:
                    # Move cursor relative to specified absolute position.
                    if params[0] is not None:
                        self._cursor_x = params[0]
                    if params[1] is not None:
                        self._cursor_y = params[1] + self._canvas.start_line
                elif command == Parser.DELETE_LINE:
                    # Delete some/all of the current line.
                    if params == 0:
                        self._print_at(
                            " " * (self._canvas.width - self._cursor_x), self._cursor_x, self._cursor_y)
                    elif params == 1:
                        self._print_at(" " * self._cursor_x, 0, self._cursor_y)
                    elif params == 2:
                        self._print_at(" " * self._canvas.width, 0, self._cursor_y)
                elif command == Parser.DELETE_CHARS:
                    # Delete n characters under the cursor.
                    for x in range(self._cursor_x, self._canvas.width):
                        if x + params < self._canvas.width:
                            cell = self._canvas.get_from(x + params, self._cursor_y)
                        else:
                            cell = (ord(" "),
                                    self._current_colours[0],
                                    self._current_colours[1],
                                    self._current_colours[2])
                        self._canvas.print_at(
                            chr(cell[0]), x, self._cursor_y, colour=cell[1], attr=cell[2], bg=cell[3])
                elif command == Parser.SHOW_CURSOR:
                    # Show/hide the cursor.
                    self._show_cursor = params
                elif command == Parser.SAVE_CURSOR:
                    # Save the cursor position.
                    self._save_cursor_x = self._cursor_x
                    self._save_cursor_y = self._cursor_y
                elif command == Parser.RESTORE_CURSOR:
                    # Restore the cursor position.
                    self._cursor_x = self._save_cursor_x
                    self._cursor_y = self._save_cursor_y
                elif command == Parser.CLEAR_SCREEN:
                    # Clear the screen.
                    self._canvas.clear_buffer(
                        self._current_colours[0], self._current_colours[1], self._current_colours[2])
                    self._cursor_x = 0
                    self._cursor_y = self._canvas.start_line
            # Move to next line, scrolling buffer as needed.
            if i != len(lines) - 1:
                self._cursor_x = 0
                self._cursor_y += 1
                if self._cursor_y - self._canvas.start_line >= self._canvas.height:
                    self._canvas.scroll()

    def _print_at(self, text, x, y):
        """
        Helper function to simplify use of the renderer.
        """
        self._canvas.print_at(
            text,
            x, y,
            colour=self._current_colours[0], attr=self._current_colours[1], bg=self._current_colours[2])


class AnsiArtPlayer(AbstractScreenPlayer):
    """
    Renderer to play ANSI art text files.

    In order to tidy up files, this must be used as a context manager (i.e. using `with`).
    """

    def __init__(self, filename, height=25, width=80, encoding="cp437", strip=False, rate=2):
        """
        :param filename: the file containingi the ANSI art.
        :param height: required height of the renderer.
        :param width: required width of the renderer.
        :param encoding: text encoding ofnthe file.
        :param strip: whether to strip CRLF from the file content.
        :param rate: number of lines to render on each update.
        """
        super(AnsiArtPlayer, self).__init__(height, width)
        self._file = open(filename, "rb")
        self._strip = strip
        self._rate = rate
        self._encoding = encoding

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._file:
            self._file.close()

    def _render_now(self):
        # Read and process the file progressively
        for _ in range(self._rate):
            line = self._file.readline()
            if not line:
                break

            # Decode the line with the specified encoding
            if isinstance(line, bytes):
                line = line.decode(self._encoding, errors='replace')

            # Strip CRLF if requested
            if self._strip and line.endswith('\r\n'):
                line = line[:-2]
            elif self._strip and line.endswith('\n'):
                line = line[:-1]

            # Play the content through the parser
            self._play_content(line)

        # Return empty lists to indicate we're using the canvas directly
        return [], []


class AsciinemaPlayer(AbstractScreenPlayer):
    """
    Renderer to play terminal recordings created by asciinema.

    This only supports the version 2 file format.  Use the max_delay setting to speed up human
    interactions (i.e. to reduce delays from typing).

    In order to tidy up files, this must be used as a context manager (i.e. using `with`).
    """

    def __init__(self, filename, height=None, width=None, max_delay=None):
        """
        :param filename: the file containingi the ANSI art.
        :param height: required height of the renderer.
        :param width: required width of the renderer.
        :param max_delay: maximum time interval (in secs) to wait between frame updates.
        """
        # Open the file and check it looks plausibly like a supported format.
        self._file = open(filename)
        header = json.loads(self._file.readline())
        if header["version"] != 2:
            raise RuntimeError("Unsupported file format")

        # Use file details if not overriden by constructor params.
        height = height if height else header["height"]
        width = width if width else header["width"]

        # Construct the full player now we have all the details.
        super(AsciinemaPlayer, self).__init__(height, width)
        self._max_delay = max_delay

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._file:
            self._file.close()

    def _render_now(self):
        self._counter += 0.05
        if self._counter >= self._next:
            if self._buffer:
                self._play_content(self._buffer)
                self._buffer = None
            while True:
                try:
                    self._next, _, self._buffer = json.loads(self._file.readline())
                    if self._next > self._counter:
                        # Speed up playback if requested.
                        if self._max_delay and self._next - self._counter > self._max_delay:
                            self._counter = self._next - self._max_delay
                        break
                    self._play_content(self._buffer)
                except ValueError:
                    # Python 3 raises a subclass of this error, so will also be caught.
                    break

        return [], []
