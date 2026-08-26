package com.siteview.app.ui

import android.content.Context
import android.graphics.Bitmap
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.GLUtils
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.PI

/**
 * نمایشگر native عکس 360 (equirectangular) با OpenGL ES.
 * کشیدن انگشت = چرخش دید، دو انگشت = زوم (تغییر FOV).
 */
class Sphere360View(context: Context, bitmap: Bitmap) : GLSurfaceView(context) {

    private val renderer = SphereRenderer(bitmap)
    private var lastX = 0f
    private var lastY = 0f

    private val scaleDetector = ScaleGestureDetector(
        context,
        object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScale(d: ScaleGestureDetector): Boolean {
                renderer.fov = (renderer.fov / d.scaleFactor).coerceIn(30f, 110f)
                requestRender()
                return true
            }
        },
    )

    init {
        setEGLContextClientVersion(2)
        setRenderer(renderer)
        renderMode = RENDERMODE_WHEN_DIRTY
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        scaleDetector.onTouchEvent(e)
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN,
            MotionEvent.ACTION_POINTER_DOWN,
            MotionEvent.ACTION_POINTER_UP,
            -> {
                lastX = e.x
                lastY = e.y
            }
            MotionEvent.ACTION_MOVE -> {
                if (e.pointerCount == 1 && !scaleDetector.isInProgress && height > 0) {
                    val perPixel = (renderer.fov * PI.toFloat() / 180f) / height
                    renderer.yaw += (e.x - lastX) * perPixel
                    renderer.pitch = (renderer.pitch + (e.y - lastY) * perPixel)
                        .coerceIn(-1.55f, 1.55f)
                    requestRender()
                }
                lastX = e.x
                lastY = e.y
            }
        }
        return true
    }
}

private class SphereRenderer(private var bitmap: Bitmap) : GLSurfaceView.Renderer {

    @Volatile var yaw = 0f
    @Volatile var pitch = 0f
    @Volatile var fov = 75f

    private var program = 0
    private var aPos = 0
    private var uYaw = 0
    private var uPitch = 0
    private var uTanFov = 0
    private var uAspect = 0
    private var aspect = 1f
    private lateinit var quad: FloatBuffer

    private val vertexShader = """
        attribute vec2 p;
        varying vec2 v;
        void main() { v = p; gl_Position = vec4(p, 0.0, 1.0); }
    """

    private val fragmentShader = """
        precision highp float;
        varying vec2 v;
        uniform sampler2D tex;
        uniform float yaw, pitch, tanFov, aspect;
        const float PI = 3.141592653589793;
        void main() {
          vec3 d = normalize(vec3(v.x * tanFov * aspect, v.y * tanFov, -1.0));
          float cp = cos(pitch), sp = sin(pitch);
          d = vec3(d.x, cp * d.y - sp * d.z, sp * d.y + cp * d.z);
          float cy = cos(yaw), sy = sin(yaw);
          d = vec3(cy * d.x + sy * d.z, d.y, -sy * d.x + cy * d.z);
          float lon = atan(d.x, -d.z);
          float lat = asin(clamp(d.y, -1.0, 1.0));
          vec2 uv = vec2(lon / (2.0 * PI) + 0.5, 0.5 - lat / PI);
          gl_FragColor = texture2D(tex, uv);
        }
    """

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        quad = ByteBuffer.allocateDirect(8 * 4)
            .order(ByteOrder.nativeOrder())
            .asFloatBuffer()
            .put(floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f))
        quad.position(0)

        program = GLES20.glCreateProgram().also { prog ->
            GLES20.glAttachShader(prog, compile(GLES20.GL_VERTEX_SHADER, vertexShader))
            GLES20.glAttachShader(prog, compile(GLES20.GL_FRAGMENT_SHADER, fragmentShader))
            GLES20.glLinkProgram(prog)
        }
        aPos = GLES20.glGetAttribLocation(program, "p")
        uYaw = GLES20.glGetUniformLocation(program, "yaw")
        uPitch = GLES20.glGetUniformLocation(program, "pitch")
        uTanFov = GLES20.glGetUniformLocation(program, "tanFov")
        uAspect = GLES20.glGetUniformLocation(program, "aspect")

        // اگر عکس از حداکثر سایز تکسچر GPU بزرگ‌تر بود، کوچکش می‌کنیم
        val maxSize = IntArray(1)
        GLES20.glGetIntegerv(GLES20.GL_MAX_TEXTURE_SIZE, maxSize, 0)
        if (maxSize[0] in 1 until bitmap.width) {
            val k = maxSize[0].toFloat() / bitmap.width
            bitmap = Bitmap.createScaledBitmap(
                bitmap, maxSize[0], (bitmap.height * k).toInt().coerceAtLeast(1), true
            )
        }

        val tex = IntArray(1)
        GLES20.glGenTextures(1, tex, 0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, tex[0])
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, bitmap, 0)
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        GLES20.glViewport(0, 0, width, height)
        aspect = if (height > 0) width.toFloat() / height else 1f
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT)
        GLES20.glUseProgram(program)
        GLES20.glEnableVertexAttribArray(aPos)
        GLES20.glVertexAttribPointer(aPos, 2, GLES20.GL_FLOAT, false, 0, quad)
        GLES20.glUniform1f(uYaw, yaw)
        GLES20.glUniform1f(uPitch, pitch)
        GLES20.glUniform1f(uTanFov, kotlin.math.tan(fov * PI.toFloat() / 360f))
        GLES20.glUniform1f(uAspect, aspect)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(aPos)
    }

    private fun compile(type: Int, source: String): Int {
        val shader = GLES20.glCreateShader(type)
        GLES20.glShaderSource(shader, source)
        GLES20.glCompileShader(shader)
        return shader
    }
}
