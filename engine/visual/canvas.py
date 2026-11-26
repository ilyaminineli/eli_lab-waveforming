from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

CANVAS_SIZE = (1920, 1440)


def _pixmap_from_image(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    qimage = QImage(
        rgba.tobytes("raw", "RGBA"),
        width,
        height,
        width * 4,
        QImage.Format.Format_RGBA8888,
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
uniform float uPreviewClock;

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
    float seconds = uPreviewClock;
    float low = uProcB.x;
    float mid = uProcB.y;
    float high = uProcB.z;
    float energy = uProcB.w;
    float spectralCentroid = uProcC.x;
    float crossSignal = uProcC.y;
    float coherence = uProcC.z;
    float transient = uProcC.w;

    vec2 p = vec2(mix(-2.4, 2.4, uv.x), mix(-1.8, 1.8, uv.y));
    float motion = seconds * (0.15 + speed * 1.8);
    float drive = energy * response;

    float fieldA = sin(
        (p.x * (8.0 + 22.0 * density)
        + sin(p.y * (4.0 + 10.0 * mid) + motion) * 1.8)
        * (1.0 + spectralCentroid)
    );
    float fieldB = cos(
        (p.y * (9.0 + 25.0 * density)
        + sin(p.x * (3.0 + 12.0 * low) - motion) * 1.6)
        * (1.0 + crossSignal)
    );
    float fieldC = sin(
        (p.x + p.y) * (4.0 + 14.0 * spectralCentroid)
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

        gpu_failed = Signal(str)

        BLEND_CODES = {
            "Normal": 0,
            "Add": 1,
            "Screen": 2,
            "Multiply": 3,
            "Difference": 4,
            "Overlay": 5,
            "Lighten": 6,
            "Darken": 7,
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
            self._gl_ready = False
            self._gl_failed = False
            self._gl_renderer = "Unknown"
            self.setMinimumSize(320, 240)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

        def set_frame(self, image: Image.Image) -> None:
            self._scene = None
            self._fallback = _pixmap_from_image(image)
            self.update()

        @property
        def gpu_ready(self) -> bool:
            return bool(self.gpu_active and self._gl_ready and not self._gl_failed)

        def set_scene(self, scene: dict) -> None:
            # Retain a complete CPU frame when one is supplied. GPU descriptors
            # do not contain pixels, so for those scenes the preview worker must
            # submit a CPU-rendered frame after GPU initialization failure.
            if all(layer.get("image") is not None for layer in scene["layers"]):
                self._fallback = _pixmap_from_image(self._flatten_scene(scene))
            self._scene = scene if self.gpu_ready else None
            if self._scene is None and self._fallback.isNull():
                self.gpu_failed.emit(
                    "GPU scene arrived before context initialization and had no CPU fallback"
                )
            self.update()

        @staticmethod
        def _flatten_scene(scene: dict) -> Image.Image:
            from engine.visual.compositor import VisualCompositor

            image = scene["background"].copy()
            for layer in scene["layers"]:
                if layer.get("image") is None:
                    continue
                VisualCompositor._blend_at(
                    image,
                    layer["image"],
                    layer["position"],
                    layer.get("blend_mode", "Normal"),
                    layer.get("opacity", 1.0),
                )
            return image

        @staticmethod
        def _gl_error_name(code: int) -> str:
            return {
                0x0500: "GL_INVALID_ENUM",
                0x0501: "GL_INVALID_VALUE",
                0x0502: "GL_INVALID_OPERATION",
                0x0505: "GL_OUT_OF_MEMORY",
                0x0506: "GL_INVALID_FRAMEBUFFER_OPERATION",
                0x0507: "GL_CONTEXT_LOST",
            }.get(int(code), f"GL error 0x{int(code):04X}")

        def _gl_check(self, operation: str) -> None:
            code = int(GL.glGetError())
            if code != GL.GL_NO_ERROR:
                raise RuntimeError(
                    f"{operation}: {self._gl_error_name(code)} (0x{code:04X}); "
                    f"renderer={self._gl_renderer}; GL={self.gl_version}"
                )

        def _gl_drain_errors(self) -> None:
            for _ in range(8):
                if int(GL.glGetError()) == GL.GL_NO_ERROR:
                    break

        @staticmethod
        def _flatten_scene(scene: dict) -> Image.Image:
            from engine.visual.compositor import VisualCompositor

            preview = scene["background"].copy()
            for layer in scene["layers"]:
                # GPU-native instruments have no CPU image. They are omitted
                # from this temporary fallback frame; the failure signal asks
                # the worker to render the complete scene through the CPU path.
                if layer.get("gpu_instrument") is not None:
                    continue
                VisualCompositor._blend_at(
                    preview,
                    layer["image"],
                    layer["position"],
                    layer.get("blend_mode", "Normal"),
                    layer.get("opacity", 1.0),
                )
            return preview

        def initializeGL(self) -> None:
            try:
                self._gl_drain_errors()
                version = GL.glGetString(GL.GL_VERSION)
                self.gl_version = (
                    version.decode("ascii", "replace") if version else "Unknown"
                )
                renderer = GL.glGetString(GL.GL_RENDERER)
                self._gl_renderer = (
                    renderer.decode("ascii", "replace") if renderer else "Unknown"
                )
                self._gl_check("initialize/context-info")
                self._program = self._build_program(VERTEX_SHADER, FRAGMENT_SHADER)
                self._gl_check("initialize/shader-program")
                vertices = np.asarray(
                    [
                        -1.0,
                        -1.0,
                        0.0,
                        1.0,
                        1.0,
                        -1.0,
                        1.0,
                        1.0,
                        -1.0,
                        1.0,
                        0.0,
                        0.0,
                        1.0,
                        1.0,
                        1.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
                self._vao = int(GL.glGenVertexArrays(1))
                self._vbo = int(GL.glGenBuffers(1))
                GL.glBindVertexArray(self._vao)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
                GL.glBufferData(
                    GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW
                )
                GL.glEnableVertexAttribArray(0)
                GL.glVertexAttribPointer(
                    0, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(0)
                )
                GL.glEnableVertexAttribArray(1)
                GL.glVertexAttribPointer(
                    1, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(8)
                )
                GL.glBindVertexArray(0)
                GL.glDisable(GL.GL_DEPTH_TEST)
                self._gl_check("initialize/vertex-array")
                self._gl_ready = True
                self._gl_failed = False
                self.gpu_active = True
                self.update()
            except Exception as exc:
                self._gl_ready = False
                self._gl_failed = True
                self.gpu_active = False
                self.gl_version = "CPU fallback"
                self._scene = None
                self.gpu_failed.emit(
                    f"GPU PREVIEW INIT FAILED · {exc} · renderer={self._gl_renderer}"
                )

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
            self._gl_drain_errors()
            rgba = image.convert("RGBA")
            width, height = rgba.size
            cached = self._textures.get(key)
            if cached is None:
                texture = int(GL.glGenTextures(1))
                self._textures[key] = (texture, (width, height))
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR
                )
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR
                )
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE
                )
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE
                )
                pixels = np.frombuffer(rgba.tobytes(), dtype=np.uint8).reshape(
                    height, width, 4
                )
                # Qt and other GL users share this context; restore neutral
                # unpack state and ensure client memory, not a PBO offset.
                GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, 0)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, 0)
                GL.glPixelStorei(GL.GL_UNPACK_SKIP_PIXELS, 0)
                GL.glPixelStorei(GL.GL_UNPACK_SKIP_ROWS, 0)
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    GL.GL_RGBA8,
                    width,
                    height,
                    0,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    pixels,
                )
                self._gl_check(f"texture/{key}/allocate-upload")
                return texture

            texture, old_size = cached
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            pixels = np.frombuffer(rgba.tobytes(), dtype=np.uint8).reshape(
                height, width, 4
            )
            GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, 0)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, 0)
            GL.glPixelStorei(GL.GL_UNPACK_SKIP_PIXELS, 0)
            GL.glPixelStorei(GL.GL_UNPACK_SKIP_ROWS, 0)
            if old_size != (width, height):
                self._textures[key] = (texture, (width, height))
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    GL.GL_RGBA8,
                    width,
                    height,
                    0,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    pixels,
                )
            else:
                GL.glTexSubImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    0,
                    0,
                    width,
                    height,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    pixels,
                )
            self._gl_check(f"texture/{key}/update")
            return texture

        def _ensure_targets(self, size: tuple[int, int]) -> None:
            self._gl_drain_errors()
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
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR
                )
                GL.glTexParameteri(
                    GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR
                )
                GL.glTexImage2D(
                    GL.GL_TEXTURE_2D,
                    0,
                    GL.GL_RGBA8,
                    width,
                    height,
                    0,
                    GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE,
                    None,
                )
                framebuffer = int(GL.glGenFramebuffers(1))
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, framebuffer)
                GL.glFramebufferTexture2D(
                    GL.GL_FRAMEBUFFER,
                    GL.GL_COLOR_ATTACHMENT0,
                    GL.GL_TEXTURE_2D,
                    texture,
                    0,
                )
                framebuffer_status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
                if framebuffer_status != GL.GL_FRAMEBUFFER_COMPLETE:
                    raise RuntimeError(
                        "GPU composition framebuffer incomplete: "
                        f"0x{int(framebuffer_status):04X}"
                    )
                self._gl_check("framebuffer/attach-color-texture")
                self._target_textures.append(texture)
                self._framebuffers.append(framebuffer)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            self._gl_check("framebuffer/complete")
            self._target_size = size

        def _uniform_location(self, name: str) -> int:
            return GL.glGetUniformLocation(self._program, name)

        def _draw_pass(
            self,
            base_texture: int,
            layer_texture: int = 0,
            rect=(0.0, 0.0, 1.0, 1.0),
            blend=0,
            opacity=1.0,
            use_layer=False,
            base_is_fbo=False,
            gpu_instrument: dict | None = None,
        ) -> None:
            self._gl_drain_errors()
            GL.glUseProgram(self._program)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, base_texture)
            GL.glUniform1i(self._uniform_location("uBase"), 0)
            GL.glUniform1i(self._uniform_location("uBaseFlip"), 1 if base_is_fbo else 0)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, layer_texture)
            GL.glUniform1i(self._uniform_location("uLayer"), 1)
            layer_kind = 0 if not use_layer else (2 if gpu_instrument else 1)
            GL.glUniform1i(self._uniform_location("uUseLayer"), layer_kind)
            GL.glUniform1i(self._uniform_location("uBlendMode"), int(blend))
            GL.glUniform1f(self._uniform_location("uOpacity"), float(opacity))
            GL.glUniform4f(self._uniform_location("uRect"), *rect)

            proc_kind = 0
            if gpu_instrument and gpu_instrument.get("kind") == "interference":
                proc_kind = 1
                params = gpu_instrument
                settings = params["settings"]
                metrics = params["metrics"]
                GL.glUniform1i(self._uniform_location("uProcKind"), proc_kind)
                GL.glUniform4f(
                    self._uniform_location("uProcA"),
                    settings["density"],
                    settings["speed"],
                    settings["response"],
                    params["seconds"],
                )
                GL.glUniform4f(
                    self._uniform_location("uProcB"),
                    metrics["low"],
                    metrics["mid"],
                    metrics["high"],
                    metrics["energy"],
                )
                GL.glUniform4f(
                    self._uniform_location("uProcC"),
                    metrics["centroid"],
                    metrics["cross"],
                    metrics["coherence"],
                    metrics["transient"],
                )
                GL.glUniform1f(
                    self._uniform_location("uProcEntropy"), metrics["entropy"]
                )
                GL.glUniform1f(
                    self._uniform_location("uPreviewClock"), params["seconds"]
                )
                ink = params["ink"]
                GL.glUniform3f(
                    self._uniform_location("uProcInk"),
                    ink[0] / 255.0,
                    ink[1] / 255.0,
                    ink[2] / 255.0,
                )
                GL.glUniform1i(
                    self._uniform_location("uProcMonochrome"),
                    1 if params["palette_mode"] == "MONOCHROME" else 0,
                )
            else:
                GL.glUniform1i(self._uniform_location("uProcKind"), 0)
                GL.glUniform1f(self._uniform_location("uPreviewClock"), 0.0)

            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)
            self._gl_check("compositor/draw-arrays")

        def paintGL(self) -> None:
            if not self.gpu_ready or self._scene is None:
                painter = QPainter(self)
                painter.fillRect(self.rect(), Qt.GlobalColor.black)
                if not self._fallback.isNull():
                    target = self._fallback.size()
                    target.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    x = (self.width() - target.width()) // 2
                    y = (self.height() - target.height()) // 2
                    painter.drawPixmap(
                        x, y, target.width(), target.height(), self._fallback
                    )
                painter.end()
                return
            try:
                background = self._scene["background"]
                width, height = background.size
                self._ensure_targets((width, height))
                # QOpenGLWidget shares a context with Qt's paint engine. Do
                # not inherit stale scissor/cull/stencil/color-mask state.
                GL.glDisable(GL.GL_BLEND)
                GL.glDisable(GL.GL_DEPTH_TEST)
                GL.glDisable(GL.GL_SCISSOR_TEST)
                GL.glDisable(GL.GL_STENCIL_TEST)
                GL.glDisable(GL.GL_CULL_FACE)
                GL.glColorMask(GL.GL_TRUE, GL.GL_TRUE, GL.GL_TRUE, GL.GL_TRUE)
                base_texture = self._texture("background", background)
                current = 0
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._framebuffers[current])
                GL.glViewport(0, 0, width, height)
                self._draw_pass(base_texture)

                for index, layer in enumerate(self._scene["layers"]):
                    gpu_instrument = layer.get("gpu_instrument")
                    if gpu_instrument is not None:
                        x, y, layer_w, layer_h = gpu_instrument["rect"]
                        texture = 0
                    else:
                        image = layer["image"]
                        x, y = layer["position"]
                        layer_w, layer_h = image.size
                        texture = self._texture(f"layer-{index}", image)

                    next_target = 1 - current
                    GL.glBindFramebuffer(
                        GL.GL_FRAMEBUFFER, self._framebuffers[next_target]
                    )
                    rect = (
                        float(x) / width,
                        float(y) / height,
                        float(layer_w) / width,
                        float(layer_h) / height,
                    )
                    # OpenGL UV origin is lower-left; convert the top-origin
                    # image-space rectangle into the framebuffer's UV space.
                    self._draw_pass(
                        self._target_textures[current],
                        texture,
                        rect,
                        self.BLEND_CODES.get(layer["blend_mode"], 0),
                        float(layer["opacity"]),
                        True,
                        True,
                        gpu_instrument=gpu_instrument,
                    )
                    current = next_target

                # QOpenGLWidget does not present to framebuffer 0. Qt owns
                # the widget target and may recreate it after every resize.
                widget_fbo = int(self.defaultFramebufferObject())
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, widget_fbo)
                GL.glClearColor(0.0, 0.0, 0.0, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                dpr = float(self.devicePixelRatioF())
                widget_w = max(1, int(round(self.width() * dpr)))
                widget_h = max(1, int(round(self.height() * dpr)))
                scale = min(widget_w / width, widget_h / height)
                view_w, view_h = int(width * scale), int(height * scale)
                GL.glViewport(
                    (widget_w - view_w) // 2, (widget_h - view_h) // 2, view_w, view_h
                )
                self._draw_pass(self._target_textures[current], base_is_fbo=True)
            except Exception as exc:
                # Disable only the failed GL path; the pre-rendered CPU frame
                # remains available to QPainter and no scene data is discarded.
                self._gl_ready = False
                self._gl_failed = True
                self.gpu_active = False
                self._scene = None
                self.gpu_failed.emit(
                    f"GPU PREVIEW FALLBACK · {exc} · renderer={self._gl_renderer}"
                )
                self.update()

else:

    class GpuCompositionCanvas(CompositionCanvas):
        """CPU-only canvas when PyOpenGL is not installed."""

        gpu_active = False
        gpu_failed = Signal(str)

        def __init__(self, assets=None, parent=None):
            super().__init__(assets, parent)
            self.setMinimumSize(320, 240)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.gl_version = "CPU fallback · PyOpenGL unavailable"
            self.gpu_ready = False

        @staticmethod
        def _flatten_scene(scene: dict) -> Image.Image:
            from engine.visual.compositor import VisualCompositor

            image = scene["background"].copy()
            for layer in scene["layers"]:
                if layer.get("image") is not None:
                    VisualCompositor._blend_at(
                        image,
                        layer["image"],
                        layer["position"],
                        layer.get("blend_mode", "Normal"),
                        layer.get("opacity", 1.0),
                    )
            return image

        def set_scene(self, scene: dict) -> None:
            self.set_frame(self._flatten_scene(scene))
