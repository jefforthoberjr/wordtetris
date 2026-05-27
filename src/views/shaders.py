import pyglet
import pyglet.text.layout

# Shapes shader - used for rectangles, lines, circles, etc.
# This is Pyglet's built-in shader for solid colored geometry.
# Vertex shader: transforms positions using window projection/view matrices
# Fragment shader: outputs solid color with opacity
def get_shape_shader():
    return pyglet.shapes.get_default_shader()


# Text shader - used for Label rendering
# This is Pyglet's built-in shader for textured text glyphs.
# Vertex shader: transforms positions, passes texture coordinates
# Fragment shader: samples font texture atlas, applies text color
def get_text_shader():
    return pyglet.text.layout.get_default_layout_shader()
