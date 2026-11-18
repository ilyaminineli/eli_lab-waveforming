from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

CANVAS_SIZE = (1920, 1440)


def _pixmap_from_image(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    qimage = QImage(
        rgba.tobytes("raw", "RGBA"), width, height,
        width * 4, QImage.Format.Format_RGBA8888,
    ).copy()
    return QPixmap.fromImage(qimage)


class CompositionCanvas(QWidget):
    """CPU compatibility canvas used when OpenGL is unavailable."""

    def __init__(self, assets=None, parent=None):
        super().__init__(parent)
        self._preview = QPixmap()
        self.setMinimumSize(500, 400)
        self.set_frame(Image.new("RGBA", (600, 450), (12, 12, 12, 255)))

    def set_frame(self, image: Image.Image) -> None:
        self._preview = _pixmap_from_image(image)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._preview.isNull():
            target = self._preview.size()
            target.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - target.width()) // 2
            y = (self.height() - target.height()) // 2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(x, y, target.width(), target.height(), self._preview)
        painter.end()


try:
    import ctypes
    import numpy as np
    from OpenGL import GL
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except Exception:  # Optional GPU dependency or platform OpenGL context.
    np = None
    GL = None
    QOpenGLWidget = None


VERTEX_SHADER = """#version 330 core
layout(location = 0) in vec2 aPosition;
layout(location = 1) in vec2 aUV;
out vec2 vUV;
void main() {
    vUV = aUV;
    gl_Position = vec4(aPosition, 0.0, 1.0);
}
"""

FRAGMENT_SHADER = """#version 330 core
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uBase;
uniform int uBaseFlip;
uniform sampler2D uLayer;
uniform int uUseLayer;
uniform int uBlendMode;
uniform float uOpacity;
uniform vec4 uRect;
uniform int uProcKind;
uniform vec4 uProcA; // density, speed, response, seconds
uniform vec4 uProcB; // low, mid, high, energy
uniform vec4 uProcC; // centroid, cross, coherence, transient
uniform float uProcEntropy;
uniform vec3 uProcInk;
uniform int uProcMonochrome;

vec3 blendColor(vec3 base, vec3 source, int mode) {
    if (mode == 1) return min(vec3(1.0), base + source);
    if (mode == 2) return 1.0 - (1.0 - base) * (1.0 - source);
    if (mode == 3) return base * source;
    if (mode == 4) return abs(base - source);
    if (mode == 5) return mix(
        2.0 * base * source,
        1.0 - 2.0 * (1.0 - base) * (1.0 - source),
        step(vec3(0.5), base)
    );
    if (mode == 6) return max(base, source);
    if (mode == 7) return min(base, source);
    return source;
}

vec4 interferenceField(vec2 uv) {
    float density = clamp(uProcA.x, 0.05, 1.0);
    float speed = uProcA.y;
    float response = uProcA.z;
    float seconds = uProcA.w;
    float low = uProcB.x;
    float mid = uProcB.y;
    float high = uProcB.z;
    float energy = uProcB.w;
    float centroid = uProcC.x;
    float crossSignal = uProcC.y;
    float coherence = uProcC.z;
    float transient = uProcC.w;

    vec2 p = vec2(mix(-2.4, 2.4, uv.x), mix(-1.8, 1.8, uv.y));
    float motion = seconds * (0.15 + speed * 1.8);
    float drive = energy * response;

    float fieldA = sin(
        (p.x * (8.0 + 22.0 * density)
        + sin(p.y * (4.0 + 10.0 * mid) + motion) * 1.8)
        * (1.0 + centroid)
    );
    float fieldB = cos(
        (p.y * (9.0 + 25.0 * density)
        + sin(p.x * (3.0 + 12.0 * low) - motion) * 1.6)
        * (1.0 + crossSignal)
    );
    float fieldC = sin(
        (p.x + p.y) * (4.0 + 14.0 * centroid)
        + motion * 1.7 + transient * 2.5
    );
    float field = fieldA + fieldB * (0.65 + coherence * 0.4) + fieldC * 0.32;
    float ridge = abs(sin(
        field * (3.0 + density * 13.0)
        + uProcEntropy * 3.0 + drive
    ));
    float threshold = 0.035 + (1.0 - density) * 0.025 + transient * 0.045;
    float alpha = ridge < threshold
        ? clamp(0.3 + (1.0 - ridge / threshold) * 0.7, 0.0, 1.0)
        : 0.0;
    float luminance = clamp(
        155.0 + (1.0 - ridge) * 95.0 + drive * 50.0 + high * 35.0,
        0.0, 255.0
    ) / 255.0;

    vec3 rgb = vec3(luminance);
    if (uProcMonochrome == 0) {
        float inkLight = 0.46 + luminance * 0.54;
        rgb = clamp(uProcInk * inkLight, 0.0, 1.0);
    }
    return vec4(rgb, alpha * (235.0 / 255.0));
}

void main() {
    vec2 baseUV = uBaseFlip == 1 ? vec2(vUV.x, 1.0 - vUV.y) : vUV;
    vec4 destination = texture(uBase, baseUV);
    if (uUseLayer == 0) {
        fragColor = destination;
        return;
    }

    vec2 localUV = (vUV - uRect.xy) / uRect.zw;
    if (localUV.x < 0.0 || localUV.y < 0.0 ||
        localUV.x > 1.0 || localUV.y > 1.0) {
        fragColor = destination;
        return;
    }

    vec4 source;
    if (uUseLayer == 2 && uProcKind == 1) {
        source = interferenceField(localUV);
    } else if (uUseLayer == 1) {
        source = texture(uLayer, localUV);
    } else {
        fragColor = destination;
        return;
    }

    source.a *= clamp(uOpacity, 0.0, 1.0);
    float outAlpha = source.a + destination.a * (1.0 - source.a);
    vec3 blended = blendColor(destination.rgb, source.rgb, uBlendMode);
    vec3 premultiplied =
        destination.rgb * destination.a * (1.0 - source.a) +
        source.rgb * source.a * (1.0 - destination.a) +
        blended * source.a * destination.a;
    vec3 outRGB = outAlpha > 0.000001 ? premultiplied / outAlpha : vec3(0.0);
    fragColor = vec4(outRGB, outAlpha);
}
"""


if GL is not None:
    class GpuCompositionCanvas(QOpenGLWidget):
        """OpenGL 3.3 layer compositor; generators can migrate to native GLSL incrementally."""

        BLEND_CODES = {
            "Normal": 0, "Add": 1, "Screen": 2, "Multiply": 3,
            "Difference": 4, "Overlay": 5, "Lighten": 6, "Darken": 7,
        }

        def __init__(self, assets=None, parent=None):
            super().__init__(parent)
            self.gpu_active = True
            self._scene = None
            self._fallback = QPixmap()
            self._program = 0
            self._vao = 0
            self._vbo = 0
            self._textures: dict[str, tuple[int, tuple[int, int]]] = {}
            self._framebuffers: list[int] = []
            self._target_textures: list[int] = []
            self._target_size = (0, 0)
            self.gl_version = "OpenGL pending"
            self.setMinimumSize(500, 400)

        def set_frame(self, image: Image.Image) -> None:
            self._scene = None
            self._fallback = _pixmap_from_image(image)
            self.update()

        def set_scene(self, scene: dict) -> None:
            # Do not flatten on the UI thread on every frame. Layer blending belongs
            # to paintGL; the CPU fallback is only prepared if OpenGL fails.
            self._scene = scene
            self.update()

        @staticmethod
        def _flatten_scene(scene: dict) -> Image.Image:
            preview = scene["background"].copy()
            for layer in scene["layers"]:
                preview.alpha_composite(layer["image"], layer["position"])
            return preview

        def initializeGL(self) -> None:
            try:
                version = GL.glGetString(GL.GL_VERSION)
                self.gl_version = version.decode("ascii", "replace") if version else "Unknown"
                self._program = self._build_program(VERTEX_SHADER, FRAGMENT_SHADER)
                vertices = np.asarray([
                    -1.0, -1.0, 0.0, 1.0,
                     1.0, -1.0, 1.0, 1.0,
                    -1.0,  1.0, 0.0, 0.0,
                     1.0,  1.0, 1.0, 0.0,
                ], dtype=np.float32)
                self._vao = int(GL.glGenVertexArrays(1))
                self._vbo = int(GL.glGenBuffers(1))
                GL.glBindVertexArray(self._vao)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
                GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)
                GL.glEnableVertexAttribArray(0)
                GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(0))
                GL.glEnableVertexAttribArray(1)
                GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(8))
                GL.glBindVertexArray(0)
                GL.glDisable(GL.GL_DEPTH_TEST)
            except Exception:
                self.gpu_active = False
                self.gl_version = "CPU fallback"
                if self._scene is not None:
                    self._fallback = _pixmap_from_image(self._flatten_scene(self._scene))
                    self._scene = None

        @staticmethod
        def _compile_shader(kind: int, source: str) -> int:
            shader = GL.glCreateShader(kind)
            GL.glShaderSource(shader, source)
            GL.glCompileShader(shader)
            if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
                message = GL.glGetShaderInfoLog(shader).decode("utf-8", "replace")
                GL.glDeleteShader(shader)
                raise RuntimeError(message)
            return int(shader)

        def _build_program(self, vertex: str, fragment: str) -> int:
            vs = self._compile_shader(GL.GL_VERTEX_SHADER, vertex)
            fs = self._compile_shader(GL.GL_FRAGMENT_SHADER, fragment)
            program = GL.glCreateProgram()
            GL.glAttachShader(program, vs)
            GL.glAttachShader(program, fs)
            GL.glLinkProgram(program)
            GL.glDeleteShader(vs)
            GL.glDeleteShader(fs)
            if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
                message = GL.glGetProgramInfoLog(program).decode("utf-8", "replace")
                GL.glDeleteProgram(program)
                raise RuntimeError(message)
            return int(program)

        def _texture(self, key: str, image: Image.Image) -> int:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            cached = self._textures.get(key)
            if cached is None:
                texture = int(GL.glGenTextures(1))
                self._textures[key] = (texture, (width, height))
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
                pixels = np.frombuffer(rgba.tobytes(), dtype=np.uint8).reshape(height, width, 4)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                    GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels,
                )
                return texture

            texture, old_size = cached
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            pixels = np.frombuffer(rgba.tobytes(), dtype=np.uint8).reshape(height, width, 4)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            if old_size != (width, height):
                self._textures[key] = (texture, (width, height))
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                    GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels,
                )
            else:
                GL.glTexSubImage2D(
                    GL.GL_TEXTURE_2D, 0, 0, 0, width, height,
                    GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels,
                )
            return texture

        def _ensure_targets(self, size: tuple[int, int]) -> None:
            if self._target_size == size and self._framebuffers:
                return
            for framebuffer in self._framebuffers:
                GL.glDeleteFramebuffers(1, [framebuffer])
            for texture in self._target_textures:
                GL.glDeleteTextures(1, [texture])
            self._framebuffers, self._target_textures = [], []
            width, height = size
            for _ in range(2):
                texture = int(GL.glGenTextures(1))
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                    GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None,
                )
                framebuffer = int(GL.glGenFramebuffers(1))
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
                GL.glFramebufferTexture2D(
                    GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                    GL.GL_TEXTURE_2D, texture, 0,
                )
                if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                    raise RuntimeError("GPU composition framebuffer is incomplete.")
                self._target_textures.append(texture)
                self._framebuffers.append(framebuffer)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
            self._target_size = size

        def _draw_pass(self, base_texture: int, layer_texture: int = 0,
                       rect=(0.0, 0.0, 1.0, 1.0), blend=0, opacity=1.0,
                       use_layer=False, base_is_fbo=False) -> None:
            GL.glUseProgram(self._program)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, base_texture)
            GL.glUniform1i(GL.glGetUniformLocation(self._program, "uBase"), 0)
            GL.glUniform1i(GL.glGetUniformLocation(self._program, "uBaseFlip"), 1 if base_is_fbo else 0)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, layer_texture)
            GL.glUniform1i(GL.glGetUniformLocation(self._program, "uLayer"), 1)
            GL.glUniform1i(GL.glGetUniformLocation(self._program, "uUseLayer"), 1 if use_layer else 0)
            GL.glUniform1i(GL.glGetUniformLocation(self._program, "uBlendMode"), int(blend))
            GL.glUniform1f(GL.glGetUniformLocation(self._program, "uOpacity"), float(opacity))
            GL.glUniform4f(GL.glGetUniformLocation(self._program, "uRect"), *rect)
            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)

        def paintGL(self) -> None:
            if not self.gpu_active or self._scene is None:
                painter = QPainter(self)
                painter.fillRect(self.rect(), Qt.GlobalColor.black)
                if not self._fallback.isNull():
                    target = self._fallback.size()
                    target.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    x = (self.width() - target.width()) // 2
                    y = (self.height() - target.height()) // 2
                    painter.drawPixmap(x, y, target.width(), target.height(), self._fallback)
                painter.end()
                return
            try:
                background = self._scene["background"]
                width, height = background.size
                self._ensure_targets((width, height))
                GL.glDisable(GL.GL_BLEND)
                GL.glDisable(GL.GL_DEPTH_TEST)
                base_texture = self._texture("background", background)
                current = 0
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._framebuffers[current])
                GL.glViewport(0, 0, width, height)
                self._draw_pass(base_texture)

                for index, layer in enumerate(self._scene["layers"]):
                    image = layer["image"]
                    x, y = layer["position"]
                    layer_w, layer_h = image.size
                    texture = self._texture(f"layer-{index}", image)
                    next_target = 1 - current
                    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._framebuffers[next_target])
                    rect = (
                        float(x) / width,
                        float(y) / height,
                        float(layer_w) / width,
                        float(layer_h) / height,
                    )
                    # OpenGL UV origin is lower-left; convert the top-origin
                    # image-space rectangle into the framebuffer's UV space.
                    self._draw_pass(
                        self._target_textures[current], texture, rect,
                        self.BLEND_CODES.get(layer["blend_mode"], 0),
                        float(layer["opacity"]), True, True,
                    )
                    current = next_target

                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
                GL.glClearColor(0.0, 0.0, 0.0, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                widget_w = max(1, self.width())
                widget_h = max(1, self.height())
                scale = min(widget_w / width, widget_h / height)
                view_w, view_h = int(width * scale), int(height * scale)
                GL.glViewport((widget_w - view_w) // 2, (widget_h - view_h) // 2, view_w, view_h)
                self._draw_pass(self._target_textures[current], base_is_fbo=True)
            except Exception:
                self.gpu_active = False
                if self._scene is not None:
                    self._fallback = _pixmap_from_image(self._flatten_scene(self._scene))
                    self._scene = None
                self.update()

else:
    class GpuCompositionCanvas(CompositionCanvas):
        """Transparent fallback when PyOpenGL is not installed."""
        gpu_active = False

        def set_scene(self, scene: dict) -> None:
            image = scene["background"].copy()
            for layer in scene["layers"]:
                image.alpha_composite(layer["image"], layer["position"])
            self.set_frame(image)
